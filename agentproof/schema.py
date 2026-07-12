"""Core data structures shared across AgentProof."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    """Severity levels for a finding, ordered from least to most severe."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MergeRecommendation(str, Enum):
    """The overall recommendation AgentProof gives for a branch."""

    APPROVE = "approve"
    REVIEW = "review"
    REJECT = "reject"


@dataclass(frozen=True)
class Finding:
    """A single issue detected by a rule."""

    rule_id: str
    severity: Severity
    title: str
    file_path: str
    line_number: int | None
    evidence: str
    recommendation: str

    def dedupe_key(self) -> tuple:
        return (self.rule_id, self.file_path, self.line_number, self.evidence)


@dataclass
class AuditReport:
    """The full result of auditing a branch against a base."""

    repo_path: str
    base: str
    branch: str
    task: str | None
    findings: list[Finding] = field(default_factory=list)
    risk_score: int = 0
    recommendation: MergeRecommendation = MergeRecommendation.APPROVE
    changed_files: list[str] = field(default_factory=list)

    def findings_by_severity(self, severity: Severity) -> list[Finding]:
        return [f for f in self.findings if f.severity == severity]

    @property
    def counts_by_severity(self) -> dict[str, int]:
        counts = {s.value: 0 for s in Severity}
        for finding in self.findings:
            counts[finding.severity.value] += 1
        return counts
