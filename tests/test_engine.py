from pathlib import Path

from agentproof.engine import calculate_risk_score, recommend, run_audit
from agentproof.schema import Finding, MergeRecommendation, Severity

DEMO_APP = str(Path(__file__).resolve().parent.parent / "demo-app")
TASK = "Fix password reset token handling"


def test_calculate_risk_score_sums_severity_points():
    findings = [
        Finding("R1", Severity.CRITICAL, "t", "f.py", 1, "e", "r"),
        Finding("R2", Severity.HIGH, "t", "f.py", 2, "e", "r"),
        Finding("R3", Severity.MEDIUM, "t", "f.py", 3, "e", "r"),
        Finding("R4", Severity.LOW, "t", "f.py", 4, "e", "r"),
    ]
    # 30 + 20 + 10 + 5 = 65
    assert calculate_risk_score(findings) == 65


def test_calculate_risk_score_caps_at_100():
    findings = [Finding(f"R{i}", Severity.CRITICAL, "t", "f.py", i, "e", "r") for i in range(10)]
    assert calculate_risk_score(findings) == 100


def test_recommend_thresholds():
    assert recommend(0) == MergeRecommendation.APPROVE
    assert recommend(29) == MergeRecommendation.APPROVE
    assert recommend(30) == MergeRecommendation.REVIEW
    assert recommend(59) == MergeRecommendation.REVIEW
    assert recommend(60) == MergeRecommendation.REJECT
    assert recommend(100) == MergeRecommendation.REJECT


def test_run_audit_rejects_ai_fix_branch():
    report = run_audit(DEMO_APP, base="main", branch="ai-fix", task=TASK)

    assert report.recommendation == MergeRecommendation.REJECT
    assert report.risk_score >= 60
    assert len(report.findings) > 0
    rule_ids = {f.rule_id for f in report.findings}
    assert "AUTH001" in rule_ids
    assert "SECRET001" in rule_ids


def test_run_audit_score_matches_manual_calculation():
    report = run_audit(DEMO_APP, base="main", branch="ai-fix", task=TASK)
    assert report.risk_score == calculate_risk_score(report.findings)


def test_run_audit_deduplicates_findings():
    report = run_audit(DEMO_APP, base="main", branch="ai-fix", task=TASK)
    keys = [f.dedupe_key() for f in report.findings]
    assert len(keys) == len(set(keys))
