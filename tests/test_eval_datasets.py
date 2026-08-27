from pathlib import Path

import pytest

from harness.eval_datasets import EvalDatasetError, EvalTarget, load_eval_targets

REPO_CONFIG = Path(__file__).parent.parent / "policy" / "eval-datasets.yaml"


def write(tmp_path, text):
    path = tmp_path / "eval-datasets.yaml"
    path.write_text(text, encoding="utf-8")
    return path


class TestLoadEvalTargets:
    def test_reads_a_dataset_and_its_reference_column(self, tmp_path):
        path = write(
            tmp_path,
            "skills:\n  dialog-summary:\n    dataset: DS1\n    reference: summary\n",
        )
        targets = load_eval_targets(path)
        assert targets["dialog-summary"] == EvalTarget(
            skill="dialog-summary", dataset_id="DS1", reference="summary"
        )

    def test_reference_is_optional(self, tmp_path):
        path = write(tmp_path, "skills:\n  to-questionnaire:\n    dataset: DS2\n")
        assert load_eval_targets(path)["to-questionnaire"].reference is None

    def test_a_skill_with_no_entry_is_simply_absent(self, tmp_path):
        # Absence means "skip the loop", not "fail the skill". Most skills have
        # no evaluation set and that is not a defect.
        path = write(tmp_path, "skills:\n  dialog-summary:\n    dataset: DS1\n")
        assert "email-composer" not in load_eval_targets(path)

    def test_an_empty_file_yields_no_targets(self, tmp_path):
        assert load_eval_targets(write(tmp_path, "skills:\n")) == {}

    def test_rejects_an_entry_with_no_dataset(self, tmp_path):
        # A typo here would silently stop the loop from ever running for this
        # skill, which looks exactly like "nothing to improve".
        path = write(tmp_path, "skills:\n  dialog-summary:\n    reference: summary\n")
        with pytest.raises(EvalDatasetError, match="dialog-summary"):
            load_eval_targets(path)

    def test_rejects_a_bare_string_entry(self, tmp_path):
        path = write(tmp_path, "skills:\n  dialog-summary: DS1\n")
        with pytest.raises(EvalDatasetError, match="dialog-summary"):
            load_eval_targets(path)


class TestRepoConfig:
    def test_the_checked_in_file_parses(self):
        targets = load_eval_targets(REPO_CONFIG)
        assert targets["dialog-summary"].reference == "summary"
        assert targets["to-questionnaire"].reference is None

    def test_email_composer_is_not_eligible(self):
        # It fails the static scan. Optimising it against a dataset would tune
        # it toward doing what it already does wrong, but better.
        assert "email-composer" not in load_eval_targets(REPO_CONFIG)


class TestEvaluatorWiring:
    def test_reads_the_evaluator_its_column_and_its_mappings(self, tmp_path):
        path = write(
            tmp_path,
            "skills:\n  s:\n    dataset: DS\n    evaluator: EV\n    eval_column: quality\n"
            "    column_mappings:\n      output: output\n",
        )
        target = load_eval_targets(path)["s"]
        assert (target.evaluator, target.eval_column) == ("EV", "quality")
        assert target.column_mappings == {"output": "output"}

    def test_rejects_an_evaluator_with_no_column_mappings(self, tmp_path):
        # The rubric names the variables it wants. Without them the evaluator
        # would run against whatever the server defaults to.
        path = write(
            tmp_path,
            "skills:\n  s:\n    dataset: DS\n    evaluator: EV\n    eval_column: quality\n",
        )
        with pytest.raises(EvalDatasetError, match="column_mappings"):
            load_eval_targets(path)

    def test_a_dataset_without_an_evaluator_is_allowed(self, tmp_path):
        # Producing outputs is useful before anyone has written a rubric.
        target = load_eval_targets(write(tmp_path, "skills:\n  s:\n    dataset: DS\n"))["s"]
        assert target.evaluator is None

    def test_rejects_an_evaluator_with_no_column(self, tmp_path):
        # Verdicts come back as eval.<column>.label; without the column name
        # the scores would be fetched and then silently unreadable.
        path = write(tmp_path, "skills:\n  s:\n    dataset: DS\n    evaluator: EV\n")
        with pytest.raises(EvalDatasetError, match="eval_column"):
            load_eval_targets(path)

    def test_the_checked_in_to_questionnaire_entry_is_wired(self):
        target = load_eval_targets(REPO_CONFIG)["to-questionnaire"]
        assert target.evaluator and target.eval_column == "questionnaire_quality"
