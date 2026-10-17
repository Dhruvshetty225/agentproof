"""Run all rules against a diff and compute the overall audit report."""

from __future__ import annotations

from dataclasses import replace

from agentproof.config import DEFAULT_REJECT_THRESHOLD, DEFAULT_REVIEW_THRESHOLD, Config
from agentproof.diff_parser import FileDiff, changed_file_paths, parse_diff
from agentproof.grouping import group_deleted_blocks
from agentproof.ignores import split_ignored
from agentproof.rules import ALL_RULES
from agentproof.schema import (
    MAX_RISK_SCORE,
    AuditReport,
    Finding,
    MergeRecommendation,
    Severity,
)

_SEVERITY_POINTS = {
    Severity.CRITICAL: 30,
    Severity.HIGH: 20,
    Severity.MEDIUM: 10,
    Severity.LOW: 5,
}


def calculate_risk_score(findings: list[Finding]) -> int:
    score = sum(_SEVERITY_POINTS[f.severity] for f in findings)
    return min(score, MAX_RISK_SCORE)


def recommend(
    risk_score: int,
    review_threshold: int = DEFAULT_REVIEW_THRESHOLD,
    reject_threshold: int = DEFAULT_REJECT_THRESHOLD,
) -> MergeRecommendation:
    if risk_score >= reject_threshold:
        return MergeRecommendation.REJECT
    if risk_score >= review_threshold:
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


def _apply_severity_overrides(findings: list[Finding], config: Config) -> list[Finding]:
    return [
        replace(f, severity=config.severity_overrides[f.rule_id])
        if f.rule_id in config.severity_overrides
        else f
        for f in findings
    ]


def collect_findings(
    file_diffs: list[FileDiff], task: str | None = None, config: Config | None = None
) -> tuple[list[Finding], list[Finding]]:
    """Run the enabled rules and return (findings to score, ignored findings).

    Order matters: ignore directives are checked line by line before deleted
    blocks are grouped, and severity overrides apply to the final findings.
    """
    config = config or Config()
    findings: list[Finding] = []
    for rule_module in ALL_RULES:
        if rule_module.RULE_ID not in config.disabled_rules:
            findings.extend(rule_module.check(file_diffs, task=task))

    findings = _deduplicate(findings)
    findings, ignored = split_ignored(findings, file_diffs)
    findings = group_deleted_blocks(findings, file_diffs)
    findings = _apply_severity_overrides(findings, config)
    return findings, ignored


def run_audit(
    repo_path: str,
    base: str,
    branch: str,
    task: str | None = None,
    config: Config | None = None,
    verifier=None,
) -> AuditReport:
    """Parse the diff between base and branch, run all rules, and score the result.

    ``verifier`` is the optional local LLM verifier (agentproof.llm_verify).
    It runs after the rules and may suppress findings; the score is computed
    from the findings that remain.
    """
    config = config or Config()
    file_diffs = parse_diff(repo_path, base, branch)
    findings, ignored = collect_findings(file_diffs, task=task, config=config)
    llm_suppressed, llm_summary = [], None
    if verifier is not None:
        findings, llm_suppressed, llm_summary = verifier.verify(findings, file_diffs, task)

    risk_score = calculate_risk_score(findings)
    recommendation = recommend(risk_score, config.review_threshold, config.reject_threshold)

    return AuditReport(
        repo_path=repo_path,
        base=base,
        branch=branch,
        task=task,
        findings=findings,
        risk_score=risk_score,
        recommendation=recommendation,
        changed_files=changed_file_paths(file_diffs),
        ignored_findings=ignored,
        config_source=config.source,
        llm_suppressed_findings=llm_suppressed,
        llm_verification=llm_summary,
    )
