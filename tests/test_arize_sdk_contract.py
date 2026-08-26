"""Guard the pinned Arize SDK against server drift.

Twice now the scan has broken without a line of this repo changing: the server
started returning a field the pinned SDK's generated model did not know, and
the model refused the whole response. Both times the symptom was a scan that
failed closed on every skill with an opaque parse error, which reads like a
judgment problem and is not one.

    8.43.1  Experiment      rejected the server's `space_id`
    8.44.0  TaskEvaluator   rejected the server's `evaluator_version_id`

These assertions name the two fields that have already bitten. They cannot
predict the next one, but they fail loudly on a downgrade and they leave a
record of what this class of breakage looks like.

The subject is the *pinned* SDK, so an environment that has not installed the
pin is skipped rather than failed: it has nothing to say about the pin.
"""

import importlib.metadata as metadata
import re
from pathlib import Path

import pytest

REQUIREMENTS = Path(__file__).parent.parent / "requirements.txt"


def pinned(package: str) -> str | None:
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        match = re.match(rf"^{re.escape(package)}==([\w.]+)\s*$", line.strip())
        if match:
            return match.group(1)
    return None


@pytest.fixture(scope="module")
def sdk():
    want = pinned("arize-ax-cli")
    assert want, "requirements.txt no longer pins arize-ax-cli"
    try:
        have_cli = metadata.version("arize-ax-cli")
    except metadata.PackageNotFoundError:
        pytest.skip("arize-ax-cli is not installed; run pip install -r requirements.txt")
    if have_cli != want:
        pytest.skip(
            f"arize-ax-cli {have_cli} installed but requirements.txt pins {want}; "
            "run pip install -r requirements.txt to check the pin"
        )
    return metadata.version("arize")


def test_task_evaluator_accepts_the_evaluator_version_the_server_returns(sdk):
    from arize._generated.api_client.models.task_evaluator import TaskEvaluator

    assert "evaluator_version_id" in TaskEvaluator.model_fields, (
        f"arize {sdk} cannot parse a task evaluator from this server. "
        "`ax tasks create-evaluation` will fail after the task is already created."
    )


def test_experiment_accepts_the_space_id_the_server_returns(sdk):
    from arize._generated.api_client.models.experiment import Experiment

    assert "space_id" in Experiment.model_fields, (
        f"arize {sdk} cannot parse an experiment from this server. "
        "`ax experiments run` and `ax experiments list` will fail."
    )
