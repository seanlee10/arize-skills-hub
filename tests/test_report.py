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
