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

    Slack section text is capped at 3000 characters. This function bounds
    the section text size by: truncating each detail to 180 chars with
    ellipsis, then accumulating findings against a 2800-char budget (leaving
    200 chars headroom for formatting and the omitted-count line). Worst case:
    with 180-char details and ~45-char overhead per line, fits ~12 findings.
    """
    # Derive skills from all findings for the fallback text
    skills = sorted({f.skill for f in findings})

    # Truncate details and accumulate within budget
    detail_truncation_limit = 180
    section_text_budget = 2800
    included_lines = []
    section_text_length = 0

    for finding in findings:
        # Truncate detail with ellipsis if needed
        detail = finding.detail
        if len(detail) > detail_truncation_limit:
            detail = detail[:detail_truncation_limit] + "…"

        line = f"• `{finding.skill}` — {finding.source}/{finding.severity}: {detail}"

        # Check if adding this line would exceed budget (account for newline separator)
        line_with_separator = "\n" + line if included_lines else line
        if section_text_length + len(line_with_separator) > section_text_budget:
            continue

        included_lines.append(line)
        section_text_length += len(line_with_separator)

    # Calculate omitted count
    omitted_count = len(findings) - len(included_lines)

    detail_lines = included_lines
    if omitted_count > 0:
        detail_lines.append(
            f"\n... and {omitted_count} more violation{'s' if omitted_count > 1 else ''}. "
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
