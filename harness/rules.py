"""policy/rules.yaml 을 로드해 SKILL.md 본문에 매칭한다."""

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
    """룰 파일을 읽어 컴파일된 Rule 목록을 돌려준다.

    파일이 없거나 형식이 깨졌으면 예외를 올린다 — 게이트가 조용히
    무력화되는 것보다 시끄럽게 깨지는 편이 안전하다.
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
    """본문에 매칭되는 모든 룰을 Finding 으로 돌려준다."""
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
