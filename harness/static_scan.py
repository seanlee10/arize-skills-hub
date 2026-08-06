"""Skill static scan entry point.

Usage:
    python -m harness.static_scan [--all] [--skill PATH] [--dry-run]
"""

import argparse
import os
import sys
from pathlib import Path

from harness.arize_judge import (
    ArizeConfig,
    JudgeError,
    Skill,
    judge_skills,
    load_arize_config,
    require_api_key,
)
from harness.findings import Finding, has_failure
from harness.report import build_slack_payload, post_slack, render_summary
from harness.rules import load_rules, scan_text
from harness.targets import select_targets

REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = REPO_ROOT / "policy" / "rules.yaml"
ARIZE_CONFIG_PATH = REPO_ROOT / "policy" / "arize.yaml"


def scan_skills(
    paths: list[Path],
    rules,
    config: ArizeConfig,
    run_id: str,
    judge_fn=judge_skills,
) -> tuple[list[str], list[Finding]]:
    """Run the rules locally, then judge whatever survived them in one batch.

    A skill that already matched a rule is not judged: its verdict is settled,
    and the round trip would buy nothing.
    """
    scanned: list[str] = []
    findings: list[Finding] = []
    to_judge: list[Skill] = []

    for path in paths:
        skill = path.parent.name
        scanned.append(skill)
        if not path.is_file():
            continue
        body = path.read_text(encoding="utf-8")
        rule_findings = scan_text(body, rules, skill)
        if rule_findings:
            findings.extend(rule_findings)
        else:
            to_judge.append(Skill(name=skill, body=body))

    try:
        findings.extend(judge_fn(to_judge, config, run_id))
    except JudgeError as exc:
        # Being unable to judge is a failure, not a pass.
        findings.extend(
            Finding(
                skill=skill.name,
                source="judge",
                severity="critical",
                detail=f"could not be judged: {exc}",
            )
            for skill in to_judge
        )

    return scanned, findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan skills for unsafe instructions.")
    parser.add_argument("--all", action="store_true", help="scan every skill, ignoring the diff")
    parser.add_argument("--skill", help="scan one skill directory (for fixtures and local work)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="judge only; skip the Slack notification and the failing exit code",
    )
    args = parser.parse_args(argv)

    rules = load_rules(RULES_PATH)
    config = load_arize_config(ARIZE_CONFIG_PATH)

    if args.skill:
        targets = [Path(args.skill) / "SKILL.md"]
    else:
        targets = select_targets(REPO_ROOT, force_all=args.all)

    scanned: list[str] = []
    findings: list[Finding] = []

    if targets:
        try:
            require_api_key()
        except JudgeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        run_id = os.environ.get("GITHUB_RUN_ID") or "local"
        scanned, findings = scan_skills(targets, rules, config, run_id)

    summary = render_summary(scanned, findings)
    print(summary)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(summary)

    failed = has_failure(findings)

    if failed and not args.dry_run:
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        run = os.environ.get("GITHUB_RUN_ID", "")
        payload = build_slack_payload(
            findings,
            commit=os.environ.get("GITHUB_SHA", "unknown")[:7],
            author=os.environ.get("GITHUB_ACTOR", "unknown"),
            run_url=f"{server}/{repo}/actions/runs/{run}",
        )
        if not post_slack(os.environ.get("SLACK_WEBHOOK_URL"), payload):
            print("warning: Slack notification was not delivered", file=sys.stderr)

    if args.dry_run:
        return 0
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
