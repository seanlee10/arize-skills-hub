"""스캔 결과의 공통 표현과 FAIL 판정 규칙."""

from dataclasses import dataclass

SEVERITIES = ("none", "low", "medium", "high", "critical")


@dataclass(frozen=True)
class Finding:
    """룰과 judge의 결과를 같은 형태로 표현한다.

    severity는 보고와 우선순위 표시 전용이며 FAIL 여부를 결정하지 않는다.
    """

    skill: str
    source: str  # "rule" | "judge"
    severity: str
    detail: str


def has_failure(findings: list[Finding]) -> bool:
    """finding이 하나라도 있으면 FAIL.

    severity 임계값을 두지 않는 이유는, 임계값이 생기는 순간
    "어느 선까지 통과시킬 것인가"라는 협상 여지가 생기고 게이트가 약해지기 때문이다.
    """
    return len(findings) > 0
