"""Run a skill against its evaluation dataset.

Usage:
    python -m harness.run_eval [--skill NAME]

With no name, every skill listed in policy/eval-datasets.yaml runs. A skill
that is not listed is not eligible and is simply not run — see
harness/eval_datasets.py for why absence and malformation differ.

This produces outputs, not scores. Scoring binds an evaluator to the
experiment the way harness/arize_judge.py does for the scan; until an
evaluator exists for a skill, the outputs are there to be read in Arize.
"""

import argparse
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from harness.arize_judge import run_cli
from harness.eval_datasets import EvalTarget, load_eval_targets
from harness.static_scan import build_run_id

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_CONFIG_PATH = REPO_ROOT / "policy" / "eval-datasets.yaml"
TASK_PATH = Path(__file__).parent / "skill_task.py"


class EvalRunError(Exception):
    """The evaluation could not be run. Distinct from a low score, which this
    module never produces: not running and running badly are different
    outcomes and must not share an exit code."""


@dataclass(frozen=True)
class EvalRun:
    skill: str
    experiment_id: str


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
) -> list[EvalRun]:
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
                )
            except Exception as exc:  # noqa: BLE001 - ax failing at all fails the run
                raise EvalRunError(f"{target.skill}: {exc}") from exc

        runs.append(EvalRun(skill=target.skill, experiment_id=experiment["id"]))
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
    try:
        runs = run_evaluations(selected, REPO_ROOT, run_id)
    except EvalRunError as exc:
        print(f"error: {exc}", file=sys.stderr)
        _write_summary(["## Skill evaluation", "", f"**Failed** — {exc}"])
        return 1

    lines = ["## Skill evaluation", "", f"Ran {len(runs)} experiment(s).", "", "| Skill | Experiment |", "|---|---|"]
    lines += [f"| `{r.skill}` | `{r.experiment_id}` |" for r in runs]
    lines += ["", "Outputs only — scoring is not wired up yet. Read them in Arize."]
    _write_summary(lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
