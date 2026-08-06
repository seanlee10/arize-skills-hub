import json
from urllib.error import URLError

from harness.findings import Finding
from harness.report import build_slack_payload, post_slack, render_summary

FINDING = Finding(
    skill="malicious-sample",
    source="rule",
    severity="critical",
    detail="instruction-override: injection phrase",
)


def test_summary_reports_pass_when_no_findings():
    text = render_summary(["dialog-summary"], [])
    assert "PASS" in text
    assert "dialog-summary" in text


def test_summary_lists_every_finding():
    text = render_summary(["malicious-sample"], [FINDING])
    assert "FAIL" in text
    assert "malicious-sample" in text
    assert "instruction-override" in text
    assert "critical" in text


def test_summary_notes_when_nothing_was_scanned():
    text = render_summary([], [])
    assert "No skills" in text


def test_summary_escapes_pipes_so_the_table_survives():
    finding = Finding(skill="s", source="judge", severity="high", detail="a | b")
    assert "a \\| b" in render_summary(["s"], [finding])


def test_slack_payload_carries_commit_author_and_link():
    payload = build_slack_payload([FINDING], "abc1234", "sean", "https://example.test/run/1")
    blob = json.dumps(payload)
    assert "abc1234" in blob
    assert "sean" in blob
    assert "https://example.test/run/1" in blob
    assert "malicious-sample" in blob
    assert "blocks" in payload


def test_post_slack_returns_false_when_webhook_missing():
    assert post_slack(None, {"text": "x"}) is False
    assert post_slack("", {"text": "x"}) is False


def test_post_slack_returns_false_on_transport_error(monkeypatch):
    def boom(*args, **kwargs):
        raise URLError("no network")

    monkeypatch.setattr("harness.report.urlopen", boom)
    assert post_slack("https://hooks.slack.test/x", {"text": "x"}) is False


def test_post_slack_returns_true_on_success(monkeypatch):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("harness.report.urlopen", lambda *a, **k: FakeResponse())
    assert post_slack("https://hooks.slack.test/x", {"text": "x"}) is True


def test_post_slack_returns_false_on_malformed_url():
    """Scheme-less URLs raise ValueError in Request.__init__, not at urlopen time.

    This is why Request construction must be inside the try block: a missing
    scheme (e.g., from stray whitespace or misconfiguration) is caught here,
    not by the transport-error test which monkeypatches urlopen and never
    exercises the Request construction path.
    """
    assert post_slack("hooks.slack.test/x", {"text": "x"}) is False


def test_slack_payload_with_realistic_detail_lengths_stays_under_3000_chars():
    """With realistic 250-char details, payload section text stays under 3000 chars.

    Slack caps section text at 3000 characters. Real judge explanations and
    rule findings with matched text can easily reach 250+ characters.
    This test verifies that truncation and budgeting prevent exceeding the limit.
    """
    # Create findings with realistic detail lengths (~250 chars each)
    realistic_detail = (
        "This skill attempts to access environment variables and send them to an external server. "
        "The instructions explicitly state to conceal this step from the user, which is a red flag. "
        "This violates the data exfiltration criterion and should be rejected for security reasons. "
    )  # 254 characters

    findings = [
        Finding(
            skill=f"skill-{i:02d}",
            source="judge" if i % 2 == 0 else "rule",
            severity="critical",
            detail=realistic_detail,
        )
        for i in range(20)
    ]

    payload = build_slack_payload(findings, "abc1234", "sean", "https://example.test/run/1")
    blob = json.dumps(payload)

    # Extract the section text that contains the findings
    section_text = None
    for block in payload["blocks"]:
        if block.get("type") == "section" and "text" in block:
            if "•" in block["text"].get("text", ""):
                section_text = block["text"]["text"]
                break

    assert section_text is not None, "Could not find findings section in payload"

    # Verify section text is under Slack's 3000 char limit
    assert len(section_text) <= 3000, (
        f"Section text is {len(section_text)} chars, exceeds 3000-char Slack limit"
    )

    # Verify not all findings fit (with 250-char details, should fit ~12)
    assert "skill-19" not in section_text, "All 20 findings should not fit in budget"

    # Verify omitted count is mentioned
    assert "more violation" in section_text
    assert "job summary" in section_text

    # Verify all skills are in the fallback text (even ones truncated from details block)
    assert "skill-19" in blob  # In the top-level text field
    assert "skill-00" in blob


def test_slack_payload_includes_all_skills_even_when_truncated():
    """Fallback text includes all skills, even those truncated from the details block.

    When findings are truncated due to size limits, the top-level text field
    should still mention all affected skills for visibility in Slack previews.
    """
    findings = [
        Finding(
            skill=f"skill-{i}",
            source="rule",
            severity="high",
            detail="x" * 250,  # Long detail that will be truncated
        )
        for i in range(20)
    ]

    payload = build_slack_payload(findings, "abc1234", "sean", "https://example.test/run/1")
    fallback_text = payload["text"]

    # All skills should be in the fallback text for visibility
    assert "skill-0" in fallback_text
    assert "skill-19" in fallback_text
    assert "skill-00" not in fallback_text  # Not zero-padded format
