"""Run a skill against its evaluation dataset.

Usage:
    python -m harness.run_eval [--skill NAME]

With no name, every skill listed in policy/eval-datasets.yaml runs. A skill
that is not listed is not eligible and is simply not run — see
harness/eval_datasets.py for why absence and malformation differ.

A skill whose entry names an evaluator is scored as well as run; one with a
dataset but no evaluator produces outputs and stops there, which is useful
before anyone has written a rubric for it. Scoring binds the evaluator to the
experiment the same way harness/arize_judge.py does for the scan.
"""

import argparse
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from harness.arize_judge import _with_retries, load_arize_config, run_cli
from harness.eval_datasets import EvalTarget, load_eval_targets
from harness.propose import (
    ProposalError,
    build_client,
    propose_improvement,
    select_evidence,
)
from harness.static_scan import build_run_id

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_CONFIG_PATH = REPO_ROOT / "policy" / "eval-datasets.yaml"
TASK_PATH = Path(__file__).parent / "skill_task.py"
ARIZE_CONFIG_PATH = REPO_ROOT / "policy" / "arize.yaml"
# Scoring waits on a server-side run, the way the scan does.
SCORE_TIMEOUT_SECONDS = 900


class EvalRunError(Exception):
    """The evaluation could not be run. Distinct from a low score, which this
    module never produces: not running and running badly are different
    outcomes and must not share an exit code."""


@dataclass(frozen=True)
class EvalRun:
    skill: str
    experiment_id: str
    score: "ScoreResult | None" = None


@dataclass(frozen=True)
class ScoreResult:
    labels: dict[str, int]
    mean: float | None
    scored: int
    unscored: int
    explanations: list[str]
    # (label, explanation) per scored row, so the improvement loop can take
    # evidence only from the rows that fell short.
    rows: list[tuple[str, str]]


def read_scores(rows: list[dict], eval_column: str) -> ScoreResult:
    """Pull the verdicts out of an experiment export.

    A row the evaluator did not label is counted, not averaged. Treating it as a
    zero would report a quality drop that nothing in the output caused.
    """
    label_key = f"eval.{eval_column}.label"
    score_key = f"eval.{eval_column}.score"
    explanation_key = f"eval.{eval_column}.explanation"

    labels: dict[str, int] = {}
    scores: list[float] = []
    explanations: list[str] = []
    paired: list[tuple[str, str]] = []
    unscored = 0

    for row in rows:
        props = row.get("additional_properties") or {}
        label = props.get(label_key)
        if not label:
            unscored += 1
            continue
        labels[label] = labels.get(label, 0) + 1
        value = props.get(score_key)
        if isinstance(value, (int, float)):
            scores.append(float(value))
        explanation = props.get(explanation_key) or ""
        if explanation:
            explanations.append(explanation)
        paired.append((label, explanation))

    return ScoreResult(
        labels=labels,
        mean=(sum(scores) / len(scores)) if scores else None,
        scored=sum(labels.values()),
        unscored=unscored,
        explanations=explanations,
        rows=paired,
    )


def score_experiment(
    target: EvalTarget,
    experiment_id: str,
    space_id: str,
    run_id: str,
    runner=run_cli,
) -> ScoreResult:
    """Bind the skill's evaluator to its experiment and read the verdicts back.

    Same shape as the scan's judge, and the same retry rule: the three mutating
    calls are not retried, because `ax` dying after the server accepted the
    request would duplicate the resource on a second attempt. Only the export is.
    """
    if not target.evaluator:
        raise EvalRunError(f"{target.skill}: no evaluator, so there is nothing to score with")

    evaluators = json.dumps(
        [{"evaluator_id": target.evaluator, "column_mappings": target.column_mappings}]
    )
    name = f"eval-{target.skill}-{run_id}"

    try:
        task = runner(
            [
                "tasks", "create-evaluation",
                "--name", name,
                "--task-type", "TEMPLATE_EVALUATION",
                "--dataset", target.dataset_id,
                "--experiment-ids", experiment_id,
                "--space", space_id,
                "--evaluators", evaluators,
            ],
            timeout=900,
        )
        triggered = runner(["tasks", "trigger-run", task["id"]], timeout=900)
        finished = _with_retries(
            runner,
            ["tasks", "wait-for-run", triggered["id"], "--timeout", str(SCORE_TIMEOUT_SECONDS)],
            timeout=SCORE_TIMEOUT_SECONDS + 60,
        )
    except Exception as exc:  # noqa: BLE001
        raise EvalRunError(f"{target.skill}: {exc}") from exc

    if finished.get("status") != "COMPLETED":
        raise EvalRunError(f"{target.skill}: scoring run ended as {finished.get('status')!r}")
    if finished.get("num_errors"):
        raise EvalRunError(f"{target.skill}: scoring reported {finished['num_errors']} errors")

    exported = _with_retries(
        runner, ["experiments", "export", experiment_id, "--stdout", "--all"]
    )
    return read_scores(exported.get("__list__", []), target.eval_column)


def select_targets_for(skill: str | None, targets: dict[str, EvalTarget]) -> list[EvalTarget]:
    """Choose which skills to run.

    No name runs everything eligible. A name that is not eligible raises rather
    than resolving to an empty list: someone who typed a skill name expects
    that skill to run, and a silent no-op reads as a completed evaluation.
    """
    if skill is None:
        return [targets[name] for name in sorted(targets)]
    if skill not in targets:
        raise EvalRunError(
            f"{skill}: no dataset in policy/eval-datasets.yaml, so it cannot be evaluated"
        )
    return [targets[skill]]


@contextmanager
def _task_env(skill_path: Path, reference: str | None):
    """Hand the task its two inputs.

    `ax experiments run --task` takes a path and passes nothing else, so the
    environment is the only channel. It is restored afterwards so a second
    target in the same process cannot inherit the first one's reference column.
    """
    previous = {k: os.environ.get(k) for k in ("SKILL_PATH", "REFERENCE_COLUMN")}
    os.environ["SKILL_PATH"] = str(skill_path)
    if reference:
        os.environ["REFERENCE_COLUMN"] = reference
    else:
        os.environ.pop("REFERENCE_COLUMN", None)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def run_evaluations(
    targets: list[EvalTarget],
    repo_root: Path,
    run_id: str,
    runner=run_cli,
    space_id: str | None = None,
) -> list[EvalRun]:
    """Run each skill against its dataset, and score the result where a rubric
    exists. A skill with a dataset but no evaluator still runs — producing
    outputs is useful before anyone has written a rubric for them."""
    runs: list[EvalRun] = []
    for target in targets:
        skill_path = Path(repo_root) / "skills" / target.skill / "SKILL.md"
        if not skill_path.is_file():
            raise EvalRunError(f"{target.skill}: no SKILL.md at {skill_path}")

        with _task_env(skill_path, target.reference):
            try:
                experiment = runner(
                    [
                        "experiments", "run",
                        "--name", f"eval-{target.skill}-{run_id}",
                        "--dataset", target.dataset_id,
                        "--task", str(TASK_PATH),
                    ],
                    timeout=1800,
                    expect="id",
                )
            except Exception as exc:  # noqa: BLE001 - ax failing at all fails the run
                raise EvalRunError(f"{target.skill}: {exc}") from exc

        experiment_id = experiment["id"]
        score = None
        if target.evaluator:
            score = score_experiment(target, experiment_id, space_id, run_id, runner=runner)

        runs.append(
            EvalRun(skill=target.skill, experiment_id=experiment_id, score=score)
        )
    return runs


def _write_summary(lines: list[str]) -> None:
    summary = "\n".join(lines) + "\n"
    print(summary)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(summary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a skill against its evaluation dataset.")
    parser.add_argument("--skill", help="one skill to evaluate; omit to run every eligible skill")
    parser.add_argument(
        "--propose",
        action="store_true",
        help="rewrite each scored SKILL.md from the evidence of the rows that fell short",
    )
    args = parser.parse_args(argv)

    targets = load_eval_targets(EVAL_CONFIG_PATH)

    try:
        selected = select_targets_for(args.skill or None, targets)
    except EvalRunError as exc:
        _write_summary(["## Skill evaluation", "", f"**Not run** — {exc}"])
        return 1

    if not selected:
        # Nothing eligible is a normal state, not a failure: it is what a newly
        # added skill looks like before anyone builds it a dataset.
        _write_summary(
            ["## Skill evaluation", "", "No skill has an evaluation dataset — nothing to run."]
        )
        return 0

    run_id = build_run_id()
    space_id = load_arize_config(ARIZE_CONFIG_PATH).space_id
    try:
        runs = run_evaluations(selected, REPO_ROOT, run_id, space_id=space_id)
    except EvalRunError as exc:
        print(f"error: {exc}", file=sys.stderr)
        _write_summary(["## Skill evaluation", "", f"**Failed** — {exc}"])
        return 1

    lines = render_summary(runs)
    if args.propose:
        lines += propose_edits(runs, selected, REPO_ROOT)
    _write_summary(lines)
    return 0


def propose_edits(runs: list[EvalRun], targets: list[EvalTarget], repo_root: Path) -> list[str]:
    """Rewrite each scored skill in place from its own shortfalls.

    Writes to the working tree and nothing else. Branching, scanning the result
    and opening the pull request are the workflow's job, so a proposal is never
    something this module can land on its own.
    """
    by_skill = {t.skill: t for t in targets}
    lines = ["", "### Proposed edits", ""]
    client = build_client()

    for run in runs:
        target = by_skill.get(run.skill)
        if run.score is None or target is None:
            continue
        evidence = select_evidence(run.score.rows, top=target.top_grade)
        if not evidence:
            lines.append(f"- `{run.skill}`: every row reached {target.top_grade}, nothing to propose")
            continue

        path = Path(repo_root) / "skills" / run.skill / "SKILL.md"
        current = path.read_text(encoding="utf-8")
        try:
            proposed = propose_improvement(current, evidence, client)
        except ProposalError as exc:
            # A failed proposal is not a failed evaluation: the scores stand.
            lines.append(f"- `{run.skill}`: no edit proposed — {exc}")
            continue

        path.write_text(proposed if proposed.endswith("\n") else proposed + "\n", encoding="utf-8")
        lines.append(
            f"- `{run.skill}`: rewritten from {len(evidence)} shortfall(s) "
            f"({len(current)} → {len(proposed)} chars)"
        )
    return lines


def render_summary(runs: list[EvalRun]) -> list[str]:
    lines = [
        "## Skill evaluation",
        "",
        f"Ran {len(runs)} experiment(s).",
        "",
        "| Skill | Grades | Mean | Experiment |",
        "|---|---|---|---|",
    ]
    for run in runs:
        score = run.score
        if score is None:
            grades, mean = "not scored", "—"
        else:
            grades = ", ".join(f"{n}× {label}" for label, n in sorted(score.labels.items()))
            if score.unscored:
                grades += f" (+{score.unscored} unscored)"
            mean = "—" if score.mean is None else f"{score.mean:.2f}"
        lines.append(f"| `{run.skill}` | {grades or '—'} | {mean} | `{run.experiment_id}` |")

    # One explanation per skill, so the summary says *why* without becoming a
    # wall of text. The rest are in Arize.
    for run in runs:
        if run.score and run.score.explanations:
            lines += ["", f"<details><summary>{run.skill} — a sample verdict</summary>", ""]
            lines += ["```", run.score.explanations[0][:1500], "```", "</details>"]

    return lines


if __name__ == "__main__":
    raise SystemExit(main())
