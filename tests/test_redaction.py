"""Secret redaction in report output.

All secrets are fabricated. Token-shaped values are built by concatenation.
"""

import io

import pytest
from rich.console import Console

from agentproof import cli
from agentproof.redaction import mask_secret, redact_report, redact_text
from agentproof.report import render_html
from agentproof.schema import AuditReport, DiffSide, Finding, Severity

FAKE_PASSWORD = "hunter2-fake-pass"
FAKE_AWS_KEY_ID = "AKIA" + "X" * 16
FAKE_KEY_BODY = "MIIEvFAKEFAKEFAKEkeybodyFAKE"
PRIVATE_KEY_LINE = (
    '"private_key": "-----BEGIN ' + "PRIVATE KEY-----\\n" + FAKE_KEY_BODY
    + "\\n-----END " + 'PRIVATE KEY-----\\n"'
)


def _finding(rule_id: str, evidence: str, line: int = 1) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=Severity.HIGH,
        title="t",
        file_path="app/config.py",
        line_number=line,
        evidence=evidence,
        recommendation="r",
        side=DiffSide.NEW,
    )


def _report(*findings: Finding, task=None) -> AuditReport:
    return AuditReport(
        repo_path=".", base="main", branch="feature", task=task, findings=list(findings)
    )


# --- the masking policy -----------------------------------------------------


@pytest.mark.parametrize(
    "secret, masked",
    [
        ("sk-1234secret", "sk-1****"),
        ("hunter2", "hunt****"),
        ("abcde", "abcd****"),
        ("abcd", "****"),
        ("abc", "****"),
        ("", "****"),
    ],
)
def test_mask_secret_shows_four_characters_or_nothing(secret, masked):
    assert mask_secret(secret) == masked


def test_redact_text_masks_whole_occurrences_only():
    text = 'secret="abc" but abcdef and xabc are different words'
    assert redact_text(text, ["abc"]) == 'secret="****" but abcdef and xabc are different words'


def test_redact_text_masks_longest_secret_first():
    text = 'a = "longsecret123" b = "longsecret"'
    result = redact_text(text, ["longsecret", "longsecret123"])
    assert result == 'a = "long****" b = "long****"'


def test_private_key_body_is_never_shown():
    result = redact_text(PRIVATE_KEY_LINE, [])
    assert FAKE_KEY_BODY not in result
    assert FAKE_KEY_BODY[:4] not in result
    assert "-----BEGIN PRIVATE KEY-----****" in result
    assert "-----END PRIVATE KEY-----" in result


def test_private_key_without_end_marker_is_masked_to_the_end():
    result = redact_text("-----BEGIN RSA " + "PRIVATE KEY-----" + FAKE_KEY_BODY, [])
    assert result == "-----BEGIN RSA PRIVATE KEY-----****"


# --- redacting a whole report ----------------------------------------------------


def test_secret_found_by_one_rule_is_hidden_in_another_rules_evidence():
    report = _report(
        _finding("SECRET001", f'db_password = "{FAKE_PASSWORD}"', line=3),
        _finding("LOG001", f'print("{FAKE_PASSWORD}")', line=9),
    )
    redacted = redact_report(report)
    for finding in redacted.findings:
        assert FAKE_PASSWORD not in finding.evidence
        assert "hunt****" in finding.evidence


def test_ignored_findings_and_task_are_redacted_too():
    report = _report(task=f"rotate {FAKE_AWS_KEY_ID}")
    report.ignored_findings = [_finding("SECRET001", f'aws = "{FAKE_AWS_KEY_ID}"')]
    redacted = redact_report(report)
    assert FAKE_AWS_KEY_ID not in redacted.task
    assert FAKE_AWS_KEY_ID not in redacted.ignored_findings[0].evidence


def test_redact_report_does_not_modify_the_original():
    report = _report(_finding("SECRET001", f'db_password = "{FAKE_PASSWORD}"'))
    redact_report(report)
    assert FAKE_PASSWORD in report.findings[0].evidence


def test_text_without_secrets_is_unchanged():
    report = _report(_finding("AUTH001", "if not user.is_authorized():"))
    assert redact_report(report).findings[0].evidence == "if not user.is_authorized():"


# --- rendered output -----------------------------------------------------------


def _secret_report() -> AuditReport:
    return _report(
        _finding("SECRET001", f'db_password = "{FAKE_PASSWORD}"', line=3),
        _finding("SECRET001", f'aws = "{FAKE_AWS_KEY_ID}"', line=4),
        _finding("SECRET001", PRIVATE_KEY_LINE, line=5),
        _finding("LOG001", f'logger.info("{FAKE_PASSWORD}")', line=9),
    )


def test_html_report_contains_no_full_secret():
    html = render_html(_secret_report())
    assert FAKE_PASSWORD not in html
    assert FAKE_AWS_KEY_ID not in html
    assert FAKE_KEY_BODY not in html
    # The masked forms are present, so the evidence really was rendered.
    assert "hunt****" in html
    assert "AKIA****" in html


def test_terminal_report_contains_no_full_secret(monkeypatch):
    output = io.StringIO()
    # Wide enough that Rich never wraps a secret across two lines, which
    # would make the "not in" checks below pass for the wrong reason.
    monkeypatch.setattr(cli, "console", Console(file=output, width=400, no_color=True))
    cli._print_terminal_report(_secret_report())
    text = output.getvalue()
    assert FAKE_PASSWORD not in text
    assert FAKE_AWS_KEY_ID not in text
    assert FAKE_KEY_BODY not in text
    assert "hunt****" in text
    assert "AKIA****" in text
