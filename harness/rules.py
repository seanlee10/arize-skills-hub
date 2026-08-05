"""Load policy/rules.yaml and match it against SKILL.md text."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from harness.findings import SEVERITIES, Finding


@dataclass(frozen=True)
class Rule:
    id: str
    pattern: re.Pattern
    severity: str
    description: str


def load_rules(path: str | Path) -> list[Rule]:
    """Read the rules file and return compiled Rule objects.

    Raises if the file is missing or malformed — a gate that silently disables
    itself is worse than one that breaks loudly.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    entries = raw["rules"]
    rules = []
    for entry in entries:
        severity = entry["severity"]
        if severity not in SEVERITIES:
            raise ValueError(f"rule {entry['id']}: unknown severity {severity!r}")
        rules.append(
            Rule(
                id=entry["id"],
                pattern=re.compile(entry["pattern"], re.IGNORECASE),
                severity=severity,
                description=entry["description"],
            )
        )
    return rules


def scan_text(text: str, rules: list[Rule], skill: str) -> list[Finding]:
    """Return a Finding for every rule that matches the text."""
    findings = []
    for rule in rules:
        match = rule.pattern.search(text)
        if match is None:
            continue
        findings.append(
            Finding(
                skill=skill,
                source="rule",
                severity=rule.severity,
                detail=f"{rule.id}: {rule.description} (matched: {match.group(0)!r})",
            )
        )
    return findings
