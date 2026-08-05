"""Judge skills with an Arize agent-as-a-judge evaluator.

The pipeline is: append the skills to the scan dataset, run an identity
experiment over them, bind an evaluation task to that experiment, trigger it,
wait for it, and read the verdicts back out of the experiment export.
"""

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import yaml

from harness.findings import Finding

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


def run_cli(args: list[str], timeout: int = 900) -> dict:
    """Run an `ax` command and parse the JSON it prints.

    `ax` writes progress lines and an upgrade banner to the same stream, so the
    JSON body is located rather than assumed to start at byte zero. A list
    response is wrapped under "__list__" so the return type stays a dict.
    """
    try:
        completed = subprocess.run(
            ["ax", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise JudgeError(f"ax {' '.join(args)} could not run: {exc}") from exc

    if completed.returncode != 0:
        raise JudgeError(
            f"ax {' '.join(args)} exited {completed.returncode}: {completed.stderr.strip()[:400]}"
        )

    out = completed.stdout
    start_obj = out.find("{")
    start_arr = out.find("[")
    candidates = [i for i in (start_obj, start_arr) if i >= 0]
    if not candidates:
        raise JudgeError(f"ax {' '.join(args)} printed no JSON")
    start = min(candidates)
    try:
        parsed = json.loads(out[start:])
    except json.JSONDecodeError as exc:
        raise JudgeError(f"ax {' '.join(args)} printed unparsable JSON: {exc}") from exc

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
    raise JudgeError(f"ax {' '.join(args)} failed after {MAX_ATTEMPTS} attempts: {last}")


def judge_skills(
    skills: list[Skill],
    config: ArizeConfig,
    run_id: str,
    runner=run_cli,
) -> list[Finding]:
    """Judge every skill in one Arize round trip.

    Returns a Finding for each skill the judge labelled FAIL, and for each skill
    that came back with no verdict at all — an unjudged skill is not a passing
    skill.
    """
    if not skills:
        return []

    examples = [{"skill_name": s.name, "skill_body": s.body} for s in skills]
    _with_retries(
        runner,
        ["datasets", "append", config.dataset_id, "--json", json.dumps(examples)],
    )

    experiment = _with_retries(
        runner,
        [
            "experiments", "run",
            "--name", f"skill-scan-{run_id}",
            "--dataset", config.dataset_id,
            "--task", str(ECHO_TASK),
        ],
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
    task = _with_retries(
        runner,
        [
            "tasks", "create-evaluation",
            "--name", f"skill-scan-{run_id}",
            "--task-type", "TEMPLATE_EVALUATION",
            "--dataset", config.dataset_id,
            "--experiment-ids", experiment_id,
            "--space", config.space_id,
            "--evaluators", evaluators,
        ],
    )

    triggered = _with_retries(runner, ["tasks", "trigger-run", task["id"]])

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

    exported = _with_retries(runner, ["experiments", "export", experiment_id, "--stdout"])
    runs = exported.get("__list__", [])

    label_key = f"eval.{config.eval_column}.label"
    explanation_key = f"eval.{config.eval_column}.explanation"

    verdicts: dict[str, tuple[str, str]] = {}
    for entry in runs:
        props = entry.get("additional_properties") or entry
        name = props.get("skill_name")
        if name is None:
            continue
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
        if label == "FAIL":
            findings.append(
                Finding(
                    skill=skill.name,
                    source="judge",
                    severity="critical",
                    detail=explanation or "judged unsafe",
                )
            )
    return findings


def require_api_key() -> None:
    """Fail loudly rather than let the gate silently disable itself."""
    if not os.environ.get("ARIZE_API_KEY"):
        raise JudgeError("ARIZE_API_KEY is not set; refusing to run the gate without a judge")
