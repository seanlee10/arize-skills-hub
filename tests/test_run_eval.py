import os

import pytest

from harness.eval_datasets import EvalTarget
from harness.run_eval import EvalRunError, run_evaluations, select_targets_for

TARGETS = {
    "dialog-summary": EvalTarget("dialog-summary", "DS1", "summary"),
    "to-questionnaire": EvalTarget("to-questionnaire", "DS2", None),
}


class FakeRunner:
    """Records each ax invocation and the env the task would have inherited."""

    def __init__(self, error=None):
        self.calls = []
        self.envs = []
        self.error = error

    def __call__(self, args, timeout=900, expect=None):
        self.calls.append(args)
        self.envs.append(
            {
                "SKILL_PATH": os.environ.get("SKILL_PATH"),
                "REFERENCE_COLUMN": os.environ.get("REFERENCE_COLUMN"),
            }
        )
        if self.error:
            raise self.error
        return {"id": f"EXP{len(self.calls)}"}


@pytest.fixture
def skills(tmp_path):
    for name in ("dialog-summary", "to-questionnaire"):
        d = tmp_path / "skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    return tmp_path


class TestSelectTargetsFor:
    def test_no_name_selects_every_eligible_skill(self):
        assert len(select_targets_for(None, TARGETS)) == 2

    def test_a_name_selects_just_that_skill(self):
        selected = select_targets_for("to-questionnaire", TARGETS)
        assert [t.skill for t in selected] == ["to-questionnaire"]

    def test_naming_an_ineligible_skill_is_an_error(self):
        # Asking for a skill that has no dataset is a mistake worth reporting:
        # silently doing nothing would look like the loop had run.
        with pytest.raises(EvalRunError, match="email-composer"):
            select_targets_for("email-composer", TARGETS)

    def test_no_name_and_no_eligible_skills_selects_nothing(self):
        assert select_targets_for(None, {}) == []


class TestRunEvaluations:
    def test_runs_one_experiment_per_target(self, skills):
        runner = FakeRunner()
        run_evaluations(list(TARGETS.values()), skills, "RUN1", runner=runner)
        assert len(runner.calls) == 2
        assert all(call[:2] == ["experiments", "run"] for call in runner.calls)

    def test_passes_the_dataset_and_the_task(self, skills):
        runner = FakeRunner()
        run_evaluations([TARGETS["to-questionnaire"]], skills, "RUN1", runner=runner)
        call = runner.calls[0]
        assert "DS2" in call
        assert any(a.endswith("skill_task.py") for a in call)

    def test_names_the_experiment_with_the_skill_and_run_id(self, skills):
        runner = FakeRunner()
        run_evaluations([TARGETS["to-questionnaire"]], skills, "RUN1", runner=runner)
        name = runner.calls[0][runner.calls[0].index("--name") + 1]
        assert "to-questionnaire" in name and "RUN1" in name

    def test_points_the_task_at_the_right_skill_file(self, skills):
        runner = FakeRunner()
        run_evaluations([TARGETS["to-questionnaire"]], skills, "RUN1", runner=runner)
        assert runner.envs[0]["SKILL_PATH"].endswith("skills/to-questionnaire/SKILL.md")

    def test_passes_the_reference_column_when_there_is_one(self, skills):
        runner = FakeRunner()
        run_evaluations(list(TARGETS.values()), skills, "RUN1", runner=runner)
        by_skill = dict(zip([c[c.index("--name") + 1] for c in runner.calls], runner.envs))
        summary_env = next(v for k, v in by_skill.items() if "dialog-summary" in k)
        questionnaire_env = next(v for k, v in by_skill.items() if "to-questionnaire" in k)
        assert summary_env["REFERENCE_COLUMN"] == "summary"
        assert not questionnaire_env["REFERENCE_COLUMN"]

    def test_does_not_leak_the_env_after_the_run(self, skills):
        run_evaluations([TARGETS["to-questionnaire"]], skills, "RUN1", runner=FakeRunner())
        assert "SKILL_PATH" not in os.environ

    def test_reports_a_missing_skill_file(self, tmp_path):
        (tmp_path / "skills").mkdir()
        with pytest.raises(EvalRunError, match="SKILL.md"):
            run_evaluations(
                [TARGETS["to-questionnaire"]], tmp_path, "RUN1", runner=FakeRunner()
            )

    def test_propagates_an_ax_failure(self, skills):
        runner = FakeRunner(error=RuntimeError("ax died"))
        with pytest.raises(EvalRunError, match="ax died"):
            run_evaluations(
                [TARGETS["to-questionnaire"]], skills, "RUN1", runner=runner
            )

    def test_returns_the_experiment_ids(self, skills):
        results = run_evaluations(list(TARGETS.values()), skills, "RUN1", runner=FakeRunner())
        assert sorted(r.experiment_id for r in results) == ["EXP1", "EXP2"]
