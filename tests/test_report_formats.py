"""JSON and HTML rendering (report.py)."""

import json

from agentproof import __version__
from agentproof.report import JSON_SCHEMA_VERSION, render_html, render_json
from agentproof.schema import AuditReport, DiffSide, Finding, MergeRecommendation, Severity

FAKE_KEY = "sk-" + "abcd1234efgh"


def _sample_report() -> AuditReport:
    return AuditReport(
        repo_path="/somewhere/private",
        base="main",
        branch="feature",
        task="Fix password reset",
        risk_score=60,
        recommendation=MergeRecommendation.REJECT,
        changed_files=["app/auth.py", "app/config.py"],
        findings=[
            Finding(
                "AUTH001", Severity.HIGH, "Security-relevant code was deleted", "app/auth.py",
                2, "if is_expired(token):\nraise ValueError('expired')", "Confirm.",
                side=DiffSide.OLD, end_line_number=3,
            ),
            Finding(
                "SECRET001", Severity.CRITICAL, "Hardcoded credential added to source code",
                "app/config.py", 1, f'api_key = "{FAKE_KEY}"', "Remove it.", side=DiffSide.NEW,
            ),
            Finding(
                "TESTCOV001", Severity.MEDIUM, "No test update", "app/auth.py, app/config.py",
                None, "Changed production files with no test changes", "Add tests.",
                paths=("app/auth.py", "app/config.py"),
            ),
        ],
        ignored_findings=[
            Finding("LOG001", Severity.HIGH, "Logged", "app/log.py", 4, "print(token)", "r",
                    side=DiffSide.NEW),
        ],
    )


# --- JSON ---------------------------------------------------------------------------


def test_json_top_level_fields():
    data = json.loads(render_json(_sample_report()))
    assert data["schema_version"] == JSON_SCHEMA_VERSION
    assert data["tool"] == {"name": "agentproof", "version": __version__}
    assert (data["base"], data["branch"], data["task"]) == ("main", "feature", "Fix password reset")
    assert data["risk_score"] == 60
    assert data["recommendation"] == "reject"
    assert data["counts_by_severity"] == {"low": 0, "medium": 1, "high": 1, "critical": 1}
    assert data["changed_files"] == ["app/auth.py", "app/config.py"]
    assert data["config_source"] == "built-in defaults"


def test_json_does_not_include_the_local_repository_path():
    assert "/somewhere/private" not in render_json(_sample_report())


def test_json_deleted_line_finding_says_its_lines_are_from_the_base():
    auth = json.loads(render_json(_sample_report()))["findings"][0]
    assert auth["side"] == "old"
    assert (auth["line_number"], auth["end_line_number"]) == (2, 3)
    assert auth["location"] == "app/auth.py:2-3 (deleted, base line numbers)"
    assert auth["files"] == ["app/auth.py"]


def test_json_added_line_and_multi_file_findings():
    findings = json.loads(render_json(_sample_report()))["findings"]
    secret, testcov = findings[1], findings[2]
    assert (secret["side"], secret["line_number"], secret["end_line_number"]) == ("new", 1, None)
    assert testcov["side"] is None
    assert testcov["line_number"] is None
    assert testcov["files"] == ["app/auth.py", "app/config.py"]


def test_json_lists_ignored_findings_separately():
    data = json.loads(render_json(_sample_report()))
    assert [f["rule_id"] for f in data["ignored_findings"]] == ["LOG001"]
    assert "LOG001" not in [f["rule_id"] for f in data["findings"]]


def test_json_is_redacted():
    text = render_json(_sample_report())
    assert FAKE_KEY not in text
    assert "sk-a****" in text


def test_json_for_an_empty_report():
    report = AuditReport(repo_path=".", base="main", branch="feature", task=None)
    data = json.loads(render_json(report))
    assert data["findings"] == []
    assert data["ignored_findings"] == []
    assert data["risk_score"] == 0
    assert data["recommendation"] == "approve"
    assert data["task"] is None


# --- HTML ------------------------------------------------------------------------------


def test_html_escapes_code_from_the_repository():
    report = AuditReport(
        repo_path=".", base="main", branch="feat<b>", task="<i>task</i>",
        findings=[
            Finding("LOG001", Severity.HIGH, "t", "app/<x>.py", 1,
                    "print('<script>alert(1)</script>')", "r", side=DiffSide.NEW),
        ],
    )
    html = render_html(report)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "feat<b>" not in html
    assert "<i>task</i>" not in html
    assert "app/&lt;x&gt;.py" in html


def test_html_shows_labelled_locations_ignored_findings_and_config():
    html = render_html(_sample_report())
    assert "app/auth.py:2-3 (deleted, base line numbers)" in html
    assert "Ignored by inline directives (1)" in html
    assert "Config: built-in defaults" in html


def test_html_is_redacted():
    html = render_html(_sample_report())
    assert FAKE_KEY not in html
    assert "sk-a****" in html


def test_html_empty_report_does_not_claim_safety():
    html = render_html(AuditReport(repo_path=".", base="main", branch="feature", task=None))
    assert "does not prove the change is safe" in html
    assert "safe to merge" not in html
