import json

import pytest

from harness.eval_datasets import EvalTarget
from harness.run_eval import EvalRunError, read_scores, score_experiment

TARGET = EvalTarget(
    skill="to-questionnaire",
    dataset_id="DS",
    reference=None,
    evaluator="EV",
    eval_column="questionnaire_quality",
    column_mappings={"situation": "situation", "output": "output"},
)

UNSCORED = EvalTarget(skill="dialog-summary", dataset_id="DS2", reference="summary")


def verdict(label, score, explanation="because"):
    return {
        "output": "a questionnaire",
        "additional_properties": {
            "eval.questionnaire_quality.label": label,
            "eval.questionnaire_quality.score": score,
            "eval.questionnaire_quality.explanation": explanation,
        },
    }


class FakeRunner:
    """Replays the four calls scoring makes, in order, and records them."""

    def __init__(self, rows=None, status="COMPLETED", num_errors=0, fail_on=None):
        self.calls = []
        self.rows = rows if rows is not None else [verdict("solid", 0.67)]
        self.status = status
        self.num_errors = num_errors
        self.fail_on = fail_on

    def __call__(self, args, timeout=900, expect=None):
        self.calls.append(args)
        head = " ".join(args[:2])
        if self.fail_on and head == self.fail_on:
            raise RuntimeError("ax blew up")
        if head == "tasks create-evaluation":
            return {"id": "TASK1"}
        if head == "tasks trigger-run":
            return {"id": "RUN1"}
        if head == "tasks wait-for-run":
            return {"status": self.status, "num_errors": self.num_errors}
        if head == "experiments export":
            return {"__list__": self.rows}
        raise AssertionError(f"unexpected call {head}")


class TestScoreExperiment:
    def test_binds_the_evaluator_to_the_experiment(self):
        runner = FakeRunner()
        score_experiment(TARGET, "EXP1", "SPACE", "RUN", runner=runner)
        create = runner.calls[0]
        assert create[:2] == ["tasks", "create-evaluation"]
        assert "EXP1" in create and "SPACE" in create
        payload = json.loads(create[create.index("--evaluators") + 1])
        assert payload[0]["evaluator_id"] == "EV"
        assert payload[0]["column_mappings"]["output"] == "output"

    def test_runs_the_four_steps_in_order(self):
        runner = FakeRunner()
        score_experiment(TARGET, "EXP1", "SPACE", "RUN", runner=runner)
        assert [" ".join(c[:2]) for c in runner.calls] == [
            "tasks create-evaluation",
            "tasks trigger-run",
            "tasks wait-for-run",
            "experiments export",
        ]

    def test_returns_the_labels_and_the_mean_score(self):
        runner = FakeRunner(rows=[verdict("solid", 0.67), verdict("excellent", 1.0)])
        result = score_experiment(TARGET, "EXP1", "SPACE", "RUN", runner=runner)
        assert result.labels == {"solid": 1, "excellent": 1}
        assert result.mean == pytest.approx(0.835)
        assert result.scored == 2

    def test_fails_when_the_run_does_not_complete(self):
        runner = FakeRunner(status="FAILED")
        with pytest.raises(EvalRunError, match="FAILED"):
            score_experiment(TARGET, "EXP1", "SPACE", "RUN", runner=runner)

    def test_fails_when_the_run_reports_errors(self):
        runner = FakeRunner(num_errors=3)
        with pytest.raises(EvalRunError, match="3"):
            score_experiment(TARGET, "EXP1", "SPACE", "RUN", runner=runner)

    def test_fails_when_binding_fails(self):
        runner = FakeRunner(fail_on="tasks create-evaluation")
        with pytest.raises(EvalRunError, match="ax blew up"):
            score_experiment(TARGET, "EXP1", "SPACE", "RUN", runner=runner)

    def test_refuses_a_target_with_no_evaluator(self):
        with pytest.raises(EvalRunError, match="no evaluator"):
            score_experiment(UNSCORED, "EXP1", "SPACE", "RUN", runner=FakeRunner())


class TestReadScores:
    def test_skips_rows_the_evaluator_did_not_label(self):
        # A row with no verdict is not a zero. Averaging it in would report a
        # quality drop that nothing in the output caused.
        rows = [verdict("solid", 0.67), {"output": "x", "additional_properties": {}}]
        result = read_scores(rows, "questionnaire_quality")
        assert result.scored == 1
        assert result.unscored == 1
        assert result.mean == pytest.approx(0.67)

    def test_reports_no_mean_when_nothing_was_scored(self):
        result = read_scores([{"output": "x", "additional_properties": {}}], "q")
        assert result.scored == 0
        assert result.mean is None

    def test_keeps_the_explanations(self):
        rows = [verdict("weak", 0.33, "compound question in Q2")]
        assert "compound question in Q2" in read_scores(rows, "questionnaire_quality").explanations[0]

    def test_pairs_each_label_with_its_explanation(self):
        rows = [verdict("solid", 0.67, "compound"), verdict("excellent", 1.0, "clean")]
        assert read_scores(rows, "questionnaire_quality").rows == [
            ("solid", "compound"),
            ("excellent", "clean"),
        ]


class TestExportPaging:
    def test_the_export_streams_every_row(self):
        # Without --all the export is one capped page, so a dataset at or over
        # the cap would silently drop the rows the grades are read from.
        runner = FakeRunner()
        score_experiment(TARGET, "EXP1", "SPACE", "RUN", runner=runner)
        export = next(c for c in runner.calls if c[:2] == ["experiments", "export"])
        assert "--all" in export
