import pytest

from harness.propose import (
    ProposalError,
    build_prompt,
    propose_improvement,
    select_evidence,
)

SKILL = "# To Questionnaire\n\n" + ("Write a questionnaire. " * 40)
EXPLANATIONS = [
    'ONE IDEA: "Are backups retained, and for how long?" joins mechanism and duration.',
    'ONE IDEA: "Can it serve queries during a rebuild, or does it need downtime?" joins two asks.',
]


class FakeBlock:
    def __init__(self, type_, text=""):
        self.type, self.text = type_, text


class FakeResponse:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [FakeBlock("text", text)]
        self.stop_reason = stop_reason
        self.stop_details = None


class FakeMessages:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, text=None, error=None, stop_reason="end_turn"):
        self.messages = FakeMessages(
            response=FakeResponse(text, stop_reason) if text is not None else None,
            error=error,
        )


class TestSelectEvidence:
    def test_keeps_only_rows_below_the_top_grade(self):
        rows = [("excellent", "flawless"), ("solid", "compound question"), ("weak", "two asks")]
        assert select_evidence(rows, top="excellent") == ["compound question", "two asks"]

    def test_returns_nothing_when_every_row_is_top_grade(self):
        # Nothing to fix is a real outcome, not an occasion to invent changes.
        assert select_evidence([("excellent", "flawless")], top="excellent") == []

    def test_ignores_rows_with_no_explanation(self):
        assert select_evidence([("weak", ""), ("solid", "real")], top="excellent") == ["real"]


class TestBuildPrompt:
    def test_carries_the_skill_and_the_evidence(self):
        prompt = build_prompt(SKILL, EXPLANATIONS)
        assert SKILL in prompt
        assert "joins mechanism and duration" in prompt

    def test_does_not_carry_the_rubric(self):
        # Handing over the grading criteria invites optimising for the grader
        # instead of fixing the skill. The quoted failures are the signal.
        prompt = build_prompt(SKILL, EXPLANATIONS)
        assert "excellent" not in prompt.lower()
        assert "rubric" not in prompt.lower()


class TestProposeImprovement:
    def test_returns_the_proposed_skill(self):
        client = FakeClient(text=SKILL + "\nNever join two asks with 'and'.")
        assert "Never join two asks" in propose_improvement(SKILL, EXPLANATIONS, client)

    def test_refuses_to_run_with_no_evidence(self):
        with pytest.raises(ProposalError, match="no evidence"):
            propose_improvement(SKILL, [], FakeClient(text=SKILL))

    def test_rejects_a_proposal_identical_to_the_original(self):
        # An empty PR wastes a reviewer's attention.
        with pytest.raises(ProposalError, match="identical"):
            propose_improvement(SKILL, EXPLANATIONS, FakeClient(text=SKILL))

    def test_rejects_a_proposal_that_guts_the_skill(self):
        # A model that returns a summary instead of an edit would silently
        # delete most of the skill, and the diff is large enough to skim past.
        with pytest.raises(ProposalError, match="rewrite or a summary"):
            propose_improvement(SKILL, EXPLANATIONS, FakeClient(text="# To Questionnaire\n"))

    def test_propagates_an_api_error(self):
        with pytest.raises(ProposalError, match="503"):
            propose_improvement(SKILL, EXPLANATIONS, FakeClient(error=RuntimeError("503")))

    def test_fails_on_truncation(self):
        client = FakeClient(text=SKILL + " more", stop_reason="max_tokens")
        with pytest.raises(ProposalError, match="truncated"):
            propose_improvement(SKILL, EXPLANATIONS, client)

    def test_strips_a_code_fence_the_model_wrapped_it_in(self):
        body = SKILL + "\nNever join two asks."
        client = FakeClient(text=f"```markdown\n{body}\n```")
        assert propose_improvement(SKILL, EXPLANATIONS, client) == body
