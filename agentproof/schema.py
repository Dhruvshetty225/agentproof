"""Core data structures shared across AgentProof."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# Risk scores range from 0 to this value (see engine.calculate_risk_score).
MAX_RISK_SCORE = 100


class Severity(str, Enum):
    """Severity levels for a finding, ordered from least to most severe."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DiffSide(str, Enum):
    """Which version of a file a finding's line number refers to."""

    OLD = "old"  # a deleted line, numbered as in the base version
    NEW = "new"  # an added line, numbered as in the branch version


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
    side: DiffSide | None = None
    # Set when several lines were merged into one finding (see grouping.py).
    end_line_number: int | None = None

    def dedupe_key(self) -> tuple:
        return (self.rule_id, self.file_path, self.line_number, self.evidence)

    @property
    def location(self) -> str:
        """Display form: path, path:line, or path:first-last for merged lines."""
        if self.line_number is None:
            return self.file_path
        if self.end_line_number is not None and self.end_line_number != self.line_number:
            return f"{self.file_path}:{self.line_number}-{self.end_line_number}"
        return f"{self.file_path}:{self.line_number}"


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
    # Findings suppressed by "agentproof: ignore[...]" directives. Not scored,
    # but still listed so reviewers can see what was silenced.
    ignored_findings: list[Finding] = field(default_factory=list)
    config_source: str = "built-in defaults"

    def findings_by_severity(self, severity: Severity) -> list[Finding]:
        return [f for f in self.findings if f.severity == severity]

    @property
    def counts_by_severity(self) -> dict[str, int]:
        counts = {s.value: 0 for s in Severity}
        for finding in self.findings:
            counts[finding.severity.value] += 1
        return counts
