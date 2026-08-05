"""The shared result type for a scan, and the rule that decides failure."""

from dataclasses import dataclass

SEVERITIES = ("none", "low", "medium", "high", "critical")


@dataclass(frozen=True)
class Finding:
    """One violation, from either the rules or the judge.

    severity is for reporting and prioritisation only; it does not decide the
    verdict.
    """

    skill: str
    source: str  # "rule" | "judge"
    severity: str
    detail: str


def has_failure(findings: list[Finding]) -> bool:
    """Any finding at all is a failure.

    There is deliberately no severity threshold: the moment a threshold exists,
    so does an argument about where to set it, and the gate gets weaker.
    """
    return len(findings) > 0
