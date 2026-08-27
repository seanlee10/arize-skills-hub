"""Propose an edit to a skill from the evidence its evaluation produced.

The input is the skill and the graders' explanations for the rows that fell
short — each of which quotes the text that decided the grade. The rubric itself
is deliberately withheld: handing over the grading criteria invites optimising
for the grader instead of fixing the skill, and the quoted failures already say
what went wrong.

The output is a whole SKILL.md, not a patch. It goes to a branch and a pull
request, so a person reads the diff before anything is merged.
"""

import re

import anthropic

MODEL = "claude-opus-5"
MAX_TOKENS = 16000
EFFORT = "high"
# A proposal this much shorter than the original is a rewrite or a summary, not
# an edit. The diff would be large enough to skim past the deletion.
MIN_LENGTH_RATIO = 0.7

FENCE_RE = re.compile(r"\A```[a-zA-Z]*\n(.*)\n```\s*\Z", re.S)


class ProposalError(Exception):
    """No usable proposal. Never returns the original unchanged: an empty pull
    request costs a reviewer attention and says nothing."""


def select_evidence(rows: list[tuple[str, str]], top: str) -> list[str]:
    """Keep the explanations for rows that did not reach the top grade."""
    return [explanation for label, explanation in rows if label != top and explanation]


def build_prompt(skill_body: str, evidence: list[str]) -> str:
    findings = "\n\n".join(f"- {e}" for e in evidence)
    return f"""A skill is a set of instructions an agent follows. This one was run against a set of test cases and a reviewer graded each result, quoting the text that decided the grade.

Here is the skill as it stands:

--- BEGIN SKILL ---
{skill_body}
--- END SKILL ---

Here is what the reviewer found:

{findings}

Rewrite the skill so an agent following it stops producing those failures.

What to change: only what the findings support. A finding that names a recurring failure is worth a change; a one-off is usually not. If the skill already states the thing being violated, restating it will not help — the instruction is present and being ignored, so the fix is to make it followable: a step that checks for the failure, a worked example of the wrong and right form, or a rule phrased so the failure is recognisable while writing.

What to preserve: the skill's purpose, its output format, its frontmatter, and its voice. Someone relying on the current behaviour should not be surprised by the new version. Keep the structure and wording that the findings do not implicate.

Return the complete new skill file and nothing else — no preamble, no explanation of your changes, no code fence."""


def propose_improvement(skill_body: str, evidence: list[str], client) -> str:
    """Ask for an edited skill and check it is one before handing it on."""
    if not evidence:
        raise ProposalError("no evidence of a shortfall, so there is nothing to propose")

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            output_config={"effort": EFFORT},
            messages=[{"role": "user", "content": build_prompt(skill_body, evidence)}],
        )
    except Exception as exc:  # noqa: BLE001
        raise ProposalError(f"model call failed: {exc}") from exc

    if response.stop_reason == "refusal":
        raise ProposalError("model refused to propose an edit")
    if response.stop_reason == "max_tokens":
        raise ProposalError(f"proposal was truncated at max_tokens={MAX_TOKENS}")

    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise ProposalError("model returned no text")

    fenced = FENCE_RE.match(text)
    if fenced:
        text = fenced.group(1)

    if text.strip() == skill_body.strip():
        raise ProposalError("proposal is identical to the current skill")
    if len(text) < len(skill_body) * MIN_LENGTH_RATIO:
        raise ProposalError(
            f"proposal is {len(text)} chars against the original's {len(skill_body)} — "
            "that is a rewrite or a summary, not an edit"
        )
    return text


def build_client():
    return anthropic.Anthropic()
