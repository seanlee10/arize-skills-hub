"""Experiment task that runs a skill against a dataset row.

The static scan judges a skill's *text*, so its task (`echo_task.py`) carries
that text through unchanged. The improvement loop judges what a skill actually
*produces*, so this task has to run it: the skill body becomes the system
prompt, the dataset row becomes the user turn, and the model's output is what
the evaluator scores.

`ax experiments run --task` takes a path and nothing else — no arguments reach
this module — so the skill under test and its dataset's reference column arrive
through the environment.
"""

import os
from pathlib import Path

import anthropic

MODEL = "claude-opus-5"
MAX_TOKENS = 16000
EFFORT = "high"


class SkillTaskError(Exception):
    """The row produced no usable output. Never returned as an empty string:
    the evaluator would score the emptiness and record an outage as a bad
    skill."""


def strip_frontmatter(text: str) -> str:
    """Drop a leading YAML frontmatter block.

    `name` and `description` route a skill to its invocation; they are not
    instructions to follow, so they do not belong in the system prompt. A body
    that has no frontmatter — as every skill registered in this repo currently
    does — is returned unchanged, and a horizontal rule further down is left
    alone because only a `---` on the very first line opens a block.
    """
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    return text[end + len("\n---") :].lstrip("\n")


def render_inputs(props: dict, reference: str | None) -> str:
    """Render a dataset row as the user turn.

    Every column is rendered under its own name rather than mapped by position,
    so a dataset with different columns needs no code change here. Sorting
    fixes the order: dict order varies with how a row was exported, and an
    input that reshuffles between runs adds noise to a before/after comparison.

    The reference column is excluded. It holds the expected answer, and a
    prompt containing the answer measures nothing.
    """
    inputs = {k: v for k, v in props.items() if k != reference}
    if not inputs:
        raise SkillTaskError(
            f"row has no input columns once the reference column {reference!r} is removed"
        )
    return "\n\n".join(f"{k}: {v}" for k, v in sorted(inputs.items()))


def run_skill(props: dict, body: str, reference: str | None, client) -> str:
    """Run one dataset row through the skill and return the model's text."""
    rendered = render_inputs(props, reference)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            output_config={"effort": EFFORT},
            system=body,
            messages=[{"role": "user", "content": rendered}],
        )
    except Exception as exc:  # noqa: BLE001 - any failure here is a failed row
        raise SkillTaskError(f"model call failed: {exc}") from exc

    # Sampling parameters are deliberately absent: Opus 5 rejects temperature,
    # top_p, and top_k with a 400. What is pinned instead is the model, the
    # effort, and the prompt — run-to-run variation remains, which is why a
    # score is only meaningful across the whole dataset, not one row.

    if response.stop_reason == "refusal":
        detail = getattr(response, "stop_details", None)
        category = getattr(detail, "category", None)
        raise SkillTaskError(f"model refused the request (category {category!r})")

    if response.stop_reason == "max_tokens":
        raise SkillTaskError(
            f"output was truncated at max_tokens={MAX_TOKENS}; "
            "a cut-off answer would be scored as a bad one"
        )

    text = "".join(b.text for b in response.content if b.type == "text")
    if not text.strip():
        raise SkillTaskError(f"response carried no text (stop_reason {response.stop_reason!r})")
    return text


def task(dataset_row):
    """Entry point for `ax experiments run --task`."""
    skill_path = os.environ.get("SKILL_PATH")
    if not skill_path:
        raise SkillTaskError("SKILL_PATH is not set; the task does not know which skill to run")

    body = strip_frontmatter(Path(skill_path).read_text(encoding="utf-8"))
    reference = os.environ.get("REFERENCE_COLUMN") or None
    props = dataset_row.get("additional_properties", dataset_row)

    return run_skill(props, body, reference, anthropic.Anthropic())
