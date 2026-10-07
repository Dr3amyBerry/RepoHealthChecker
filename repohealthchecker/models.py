"""Modelos tipados de auditoría y serialización estable."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class CheckResult:
    identifier: str
    name: str
    category: str
    status: Status
    weight: int
    explanation: str
    recommendation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "name": self.name,
            "category": self.category,
            "status": self.status.value,
            "weight": self.weight,
            "explanation": self.explanation,
            "recommendation": self.recommendation,
        }


@dataclass(frozen=True)
class AuditReport:
    repository: str
    generated_at: str
    score: int | None
    evaluated_weight: int
    total_weight: int
    checks: tuple[CheckResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "repository": self.repository,
            "generated_at": self.generated_at,
            "score": self.score,
            "evaluated_weight": self.evaluated_weight,
            "total_weight": self.total_weight,
            "checks": [check.to_dict() for check in self.checks],
            "summary": {
                status.value: sum(check.status == status for check in self.checks)
                for status in Status
            },
        }
