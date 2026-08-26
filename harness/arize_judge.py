"""Judge skills with an Arize agent-as-a-judge evaluator.

The pipeline is: append the skills to the scan dataset, run an identity
experiment over them, bind an evaluation task to that experiment, trigger it,
wait for it, and read the verdicts back out of the experiment export — joined
to a skill through the dataset export, since the experiment export carries no
input columns, only a top-level example_id.
"""

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import yaml

from harness.findings import Finding

# Colour codes contain "[", which the JSON search below would otherwise
# mistake for the start of a JSON array.
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

MAX_ATTEMPTS = 3
WAIT_TIMEOUT_SECONDS = 600
ECHO_TASK = Path(__file__).parent / "echo_task.py"


class JudgeError(Exception):
    """The pipeline could not produce a verdict. Callers treat this as FAIL."""


class Skill(NamedTuple):
    name: str
    body: str


@dataclass(frozen=True)
class ArizeConfig:
    space_id: str
    dataset_id: str
    evaluator_id: str
    eval_column: str


def load_arize_config(path: str | Path) -> ArizeConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return ArizeConfig(
        space_id=raw["space_id"],
        dataset_id=raw["dataset_id"],
        evaluator_id=raw["evaluator_id"],
        eval_column=raw["eval_column"],
    )


def _command_label(args: list[str]) -> str:
    """Name the ax command without echoing its payload.

    Argument values carry whole skill bodies. Putting the full command line into
    an error message pushes those into the Slack notification and the job
    summary, which is both unreadable and a needless place for skill text to
    end up. The subcommand plus the CLI's own stderr is what a reader needs.
    """
    subcommand = " ".join(args[:2]) if args else ""
    return f"ax {subcommand}".strip()


def run_cli(args: list[str], timeout: int = 900) -> dict:
    """Run an `ax` command and parse the JSON it prints.

    `ax` writes progress lines and an upgrade banner to the same stream, so the
    JSON body is located rather than assumed to start at byte zero. A list
    response is wrapped under "__list__" so the return type stays a dict.

    Colour codes are stripped before that search. "\\x1b[91m" contains a "[",
    so a coloured line ahead of the JSON reads as the start of a JSON array:
    `ax` exits 0 and prints a red traceback when task rows raise, and the
    resulting "unparsable JSON" replaced the traceback that said what actually
    went wrong.
    """
    try:
        completed = subprocess.run(
            ["ax", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise JudgeError(f"{_command_label(args)} could not run: {exc}") from exc

    if completed.returncode != 0:
        raise JudgeError(
            f"{_command_label(args)} exited {completed.returncode}: "
            f"{completed.stderr.strip()[:400]}"
        )

    out = ANSI_RE.sub("", completed.stdout)
    start_obj = out.find("{")
    start_arr = out.find("[")
    candidates = [i for i in (start_obj, start_arr) if i >= 0]
    if not candidates:
        # The tail, not the command: when ax prints a traceback instead of a
        # result, that traceback is the only thing that says why.
        raise JudgeError(
            f"{_command_label(args)} printed no JSON. Last output:\n{out.strip()[-600:]}"
        )
    start = min(candidates)
    try:
        parsed = json.loads(out[start:])
    except json.JSONDecodeError as exc:
        raise JudgeError(f"{_command_label(args)} printed unparsable JSON: {exc}") from exc

    return {"__list__": parsed} if isinstance(parsed, list) else parsed


def _with_retries(runner, args, timeout=900):
    last: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        if attempt:
            time.sleep(2**attempt)
        try:
            return runner(args, timeout=timeout)
        except JudgeError as exc:
            last = exc
    raise JudgeError(f"{_command_label(args)} failed after {MAX_ATTEMPTS} attempts: {last}")


def judge_skills(
    skills: list[Skill],
    config: ArizeConfig,
    run_id: str,
    runner=run_cli,
) -> list[Finding]:
    """Judge every skill in one Arize round trip.

    Returns a Finding for each skill the judge labelled anything other than
    PASS, and for each skill that came back with no row for this run at all
    — an unjudged skill is not a passing skill.

    The experiment export does not carry the dataset's input columns (no
    skill_name, no scan_run_id) — only eval.* verdict fields, trace ids, and
    a top-level example_id. So the join to a skill goes through the dataset:
    the dataset is exported separately to build example_id -> skill_name for
    this run's own examples (scan_run_id == run_id, which also keeps a stale
    example appended by an earlier run on the shared, long-lived dataset
    from leaking its verdict into this run), and each experiment-export row
    is then matched to a skill via that map.

    The four mutating calls below (dataset append, experiment run, task
    creation, trigger) are deliberately *not* retried: if `ax` dies locally
    after the server already accepted the request, retrying would duplicate
    the resource. They fail closed on the first error instead — a JudgeError
    propagates immediately and the caller treats that as FAIL. Only the
    read-only calls (wait-for-run, and the two exports) are retried.
    """
    if not skills:
        return []

    examples = [
        {"skill_name": s.name, "skill_body": s.body, "scan_run_id": run_id}
        for s in skills
    ]
    runner(
        ["datasets", "append", config.dataset_id, "--json", json.dumps(examples)],
        timeout=900,
    )

    experiment = runner(
        [
            "experiments", "run",
            "--name", f"skill-scan-{run_id}",
            "--dataset", config.dataset_id,
            "--task", str(ECHO_TASK),
        ],
        timeout=900,
    )
    experiment_id = experiment["id"]

    evaluators = json.dumps(
        [
            {
                "evaluator_id": config.evaluator_id,
                "column_mappings": {
                    "skill_name": "skill_name",
                    "skill_body": "skill_body",
                },
            }
        ]
    )
    task = runner(
        [
            "tasks", "create-evaluation",
            "--name", f"skill-scan-{run_id}",
            "--task-type", "TEMPLATE_EVALUATION",
            "--dataset", config.dataset_id,
            "--experiment-ids", experiment_id,
            "--space", config.space_id,
            "--evaluators", evaluators,
        ],
        timeout=900,
    )

    triggered = runner(["tasks", "trigger-run", task["id"]], timeout=900)

    # wait-for-run takes the run id only; passing the task id as well is an error.
    finished = _with_retries(
        runner,
        ["tasks", "wait-for-run", triggered["id"], "--timeout", str(WAIT_TIMEOUT_SECONDS)],
        timeout=WAIT_TIMEOUT_SECONDS + 60,
    )
    if finished.get("status") != "COMPLETED":
        raise JudgeError(f"evaluation run ended as {finished.get('status')!r}")
    if finished.get("num_errors"):
        raise JudgeError(f"evaluation run reported {finished['num_errors']} errors")

    # The dataset carries the input columns (skill_name, skill_body,
    # scan_run_id) under each example's additional_properties, keyed by the
    # example's top-level id. Only examples from this run are kept, so a
    # stale example from an earlier run on the shared dataset can never
    # supply this run's verdict for a same-named skill.
    dataset_export = _with_retries(runner, ["datasets", "export", config.dataset_id, "--stdout"])
    example_to_skill: dict[str, str] = {}
    for row in dataset_export.get("__list__", []):
        props = row.get("additional_properties") or {}
        if props.get("scan_run_id") != run_id:
            continue
        example_id = row.get("id")
        name = props.get("skill_name")
        if example_id is None or name is None:
            continue
        example_to_skill[example_id] = name

    exported = _with_retries(runner, ["experiments", "export", experiment_id, "--stdout"])
    runs = exported.get("__list__", [])

    label_key = f"eval.{config.eval_column}.label"
    explanation_key = f"eval.{config.eval_column}.explanation"

    verdicts: dict[str, tuple[str | None, str]] = {}
    for entry in runs:
        example_id = entry.get("example_id")
        if example_id is None:
            continue
        name = example_to_skill.get(example_id)
        if name is None:
            # No example in this run's own set produced this row: either it
            # belongs to a different run or the id is otherwise unknown.
            continue
        props = entry.get("additional_properties") or {}
        verdicts[name] = (props.get(label_key), props.get(explanation_key) or "")

    findings = []
    for skill in skills:
        if skill.name not in verdicts:
            findings.append(
                Finding(
                    skill=skill.name,
                    source="judge",
                    severity="critical",
                    detail="no verdict returned for this skill",
                )
            )
            continue
        label, explanation = verdicts[skill.name]
        # Anything other than an explicit PASS is a failure: a missing,
        # empty, or unrecognized label is not evidence of safety.
        if label == "PASS":
            continue
        if not label:
            detail = "skill was not judged: no label was returned"
        else:
            detail = explanation or "judged unsafe"
        findings.append(
            Finding(
                skill=skill.name,
                source="judge",
                severity="critical",
                detail=detail,
            )
        )
    return findings


def require_api_key() -> None:
    """Fail loudly rather than let the gate silently disable itself."""
    if not os.environ.get("ARIZE_API_KEY"):
        raise JudgeError("ARIZE_API_KEY is not set; refusing to run the gate without a judge")
