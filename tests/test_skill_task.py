import pytest

from harness.skill_task import (
    SkillTaskError,
    render_inputs,
    run_skill,
    strip_frontmatter,
)

BODY = "Turn the situation into a questionnaire."


class FakeBlock:
    def __init__(self, type_, text=""):
        self.type = type_
        self.text = text


class FakeResponse:
    def __init__(self, blocks, stop_reason="end_turn"):
        self.content = blocks
        self.stop_reason = stop_reason
        self.stop_details = None


class FakeMessages:
    """Records the request and replays a canned response, or raises."""

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, response=None, error=None):
        self.messages = FakeMessages(response=response, error=error)


def ok_client(text="# Questionnaire\n\n## Context\n"):
    return FakeClient(response=FakeResponse([FakeBlock("text", text)]))


class TestStripFrontmatter:
    def test_removes_yaml_frontmatter(self):
        body = strip_frontmatter(
            "---\nname: to-questionnaire\ndescription: Turn a decision...\n---\n\n" + BODY
        )
        assert body == BODY
        assert "description:" not in body

    def test_leaves_a_body_without_frontmatter_untouched(self):
        # The skills already registered in this repo start straight at a heading.
        body = "# Email Composer\n\n## Description\n\nDraft an email."
        assert strip_frontmatter(body) == body

    def test_does_not_treat_a_horizontal_rule_as_frontmatter(self):
        body = "# Title\n\n---\n\nSection two."
        assert strip_frontmatter(body) == body


class TestRenderInputs:
    def test_renders_every_column(self):
        rendered = render_inputs({"situation": "S", "recipient": "R"}, reference=None)
        assert "situation: S" in rendered
        assert "recipient: R" in rendered

    def test_orders_columns_deterministically(self):
        forward = render_inputs({"a": "1", "b": "2", "c": "3"}, reference=None)
        reverse = render_inputs({"c": "3", "b": "2", "a": "1"}, reference=None)
        assert forward == reverse

    def test_excludes_the_reference_column(self):
        # samsum_small carries `summary` as the answer. Rendering it would put
        # the answer in the prompt and the experiment would measure nothing.
        rendered = render_inputs(
            {"dialogue": "A: hi\nB: hey", "summary": "They greet."},
            reference="summary",
        )
        assert "dialogue:" in rendered
        assert "They greet." not in rendered

    def test_rejects_a_row_with_nothing_left_to_send(self):
        with pytest.raises(SkillTaskError, match="no input columns"):
            render_inputs({"summary": "They greet."}, reference="summary")


class TestRunSkill:
    def test_returns_the_models_text(self):
        client = ok_client("the questionnaire")
        assert run_skill({"situation": "S"}, BODY, None, client) == "the questionnaire"

    def test_sends_the_skill_body_as_the_system_prompt(self):
        client = ok_client()
        run_skill({"situation": "S"}, BODY, None, client)
        assert client.messages.calls[0]["system"] == BODY

    def test_sends_the_rendered_row_as_the_user_turn(self):
        client = ok_client()
        run_skill({"situation": "S"}, BODY, None, client)
        messages = client.messages.calls[0]["messages"]
        assert messages == [{"role": "user", "content": "situation: S"}]

    def test_never_sends_sampling_parameters(self):
        # Opus 5 rejects temperature/top_p/top_k with a 400. Determinism has to
        # come from a pinned model and a pinned prompt, not from sampling.
        client = ok_client()
        run_skill({"situation": "S"}, BODY, None, client)
        sent = client.messages.calls[0]
        assert not {"temperature", "top_p", "top_k"} & set(sent)

    def test_pins_the_model_and_effort(self):
        client = ok_client()
        run_skill({"situation": "S"}, BODY, None, client)
        sent = client.messages.calls[0]
        assert sent["model"] == "claude-opus-5"
        assert sent["output_config"] == {"effort": "high"}

    def test_propagates_an_api_error(self):
        # Returning "" here would hand the evaluator an empty output to score,
        # and an outage would be recorded as a bad skill.
        client = FakeClient(error=RuntimeError("503"))
        with pytest.raises(SkillTaskError, match="503"):
            run_skill({"situation": "S"}, BODY, None, client)

    def test_fails_on_a_refusal(self):
        client = FakeClient(response=FakeResponse([], stop_reason="refusal"))
        with pytest.raises(SkillTaskError, match="refus"):
            run_skill({"situation": "S"}, BODY, None, client)

    def test_fails_when_the_response_carries_no_text(self):
        client = FakeClient(response=FakeResponse([FakeBlock("thinking")]))
        with pytest.raises(SkillTaskError, match="no text"):
            run_skill({"situation": "S"}, BODY, None, client)

    def test_fails_when_the_output_was_truncated(self):
        # A questionnaire cut off mid-section would be scored as a bad answer.
        client = FakeClient(
            response=FakeResponse([FakeBlock("text", "half a doc")], stop_reason="max_tokens")
        )
        with pytest.raises(SkillTaskError, match="truncated"):
            run_skill({"situation": "S"}, BODY, None, client)
