"""Render scan results as a job summary and a Slack notification."""

import json
from urllib.error import URLError
from urllib.request import Request, urlopen

from harness.findings import Finding


def render_summary(scanned: list[str], findings: list[Finding]) -> str:
    """Markdown written on every run, pass or fail.

    Writing it unconditionally is what lets a quiet Slack channel be read as
    "nothing was wrong" rather than "the workflow is broken".
    """
    lines = ["## Skill static scan", ""]

    if not scanned:
        lines.append("No skills matched this commit — nothing to scan.")
        return "\n".join(lines) + "\n"

    status = "FAIL" if findings else "PASS"
    lines.append(f"**Result: {status}** — {len(scanned)} skill(s) scanned")
    lines.append("")
    for name in scanned:
        lines.append(f"- `{name}`")
    lines.append("")

    if not findings:
        lines.append("No violations detected.")
        return "\n".join(lines) + "\n"

    lines.append("### Violations")
    lines.append("")
    lines.append("| Skill | Source | Severity | Detail |")
    lines.append("|---|---|---|---|")
    for finding in findings:
        detail = finding.detail.replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{finding.skill}` | {finding.source} | {finding.severity} | {detail} |"
        )
    lines.append("")
    lines.append("Severity is reported for prioritisation only; it does not decide the verdict.")
    return "\n".join(lines) + "\n"


def build_slack_payload(
    findings: list[Finding],
    commit: str,
    author: str,
    run_url: str,
) -> dict:
    """Block Kit payload, sent only when the scan failed.

    Slack section text is capped at 3000 characters. This function limits
    findings to 15 (conservatively under ~2000 chars) and appends an omitted
    count if more exist, ensuring the payload never exceeds Slack's limit.
    """
    max_findings = 15
    included = findings[:max_findings]
    skills = sorted({f.skill for f in included})
    detail_lines = [
        f"• `{f.skill}` — {f.source}/{f.severity}: {f.detail}" for f in included
    ]

    if len(findings) > max_findings:
        omitted = len(findings) - max_findings
        detail_lines.append(
            f"\n... and {omitted} more violation{'s' if omitted > 1 else ''}. "
            f"See the job summary for the complete list."
        )

    return {
        "text": f"Skill static scan failed: {', '.join(skills)}",
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "🚨 Skill static scan failed"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Commit*\n`{commit}`"},
                    {"type": "mrkdwn", "text": f"*Author*\n{author}"},
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(detail_lines)},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"<{run_url}|View the Actions run>"},
            },
        ],
    }


def post_slack(webhook_url: str | None, payload: dict) -> bool:
    """Send to Slack. Never raises.

    A notification failure must not overturn the verdict, so the caller logs the
    return value and leaves the exit code to the scan result.
    """
    if not webhook_url:
        return False
    try:
        request = Request(
            webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=10) as response:
            return 200 <= response.status < 300
    except (URLError, OSError, ValueError):
        return False
