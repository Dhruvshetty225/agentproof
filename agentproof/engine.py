"""Run all rules against a diff and compute the overall audit report."""

from __future__ import annotations

from agentproof.diff_parser import changed_file_paths, parse_diff
from agentproof.rules import ALL_RULES
from agentproof.schema import AuditReport, Finding, MergeRecommendation, Severity

_SEVERITY_POINTS = {
    Severity.CRITICAL: 30,
    Severity.HIGH: 20,
    Severity.MEDIUM: 10,
    Severity.LOW: 5,
}

_MAX_SCORE = 100
_REVIEW_THRESHOLD = 30
_REJECT_THRESHOLD = 60


def calculate_risk_score(findings: list[Finding]) -> int:
    score = sum(_SEVERITY_POINTS[f.severity] for f in findings)
    return min(score, _MAX_SCORE)


def recommend(risk_score: int) -> MergeRecommendation:
    if risk_score >= _REJECT_THRESHOLD:
        return MergeRecommendation.REJECT
    if risk_score >= _REVIEW_THRESHOLD:
        return MergeRecommendation.REVIEW
    return MergeRecommendation.APPROVE


def _deduplicate(findings: list[Finding]) -> list[Finding]:
    seen = set()
    unique: list[Finding] = []
    for finding in findings:
        key = finding.dedupe_key()
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return unique


def run_audit(repo_path: str, base: str, branch: str, task: str | None = None) -> AuditReport:
    """Parse the diff between base and branch, run all rules, and score the result."""
    file_diffs = parse_diff(repo_path, base, branch)

    findings: list[Finding] = []
    for rule_module in ALL_RULES:
        findings.extend(rule_module.check(file_diffs, task=task))

    findings = _deduplicate(findings)
    risk_score = calculate_risk_score(findings)
    recommendation = recommend(risk_score)

    return AuditReport(
        repo_path=repo_path,
        base=base,
        branch=branch,
        task=task,
        findings=findings,
        risk_score=risk_score,
        recommendation=recommendation,
        changed_files=changed_file_paths(file_diffs),
    )
