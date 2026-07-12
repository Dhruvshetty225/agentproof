from pathlib import Path

from agentproof.diff_parser import ChangedLine, FileDiff, parse_diff
from agentproof.rules import (
    auth,
    logging_safety,
    secrets,
    test_coverage,
    unrelated_changes,
    unreviewable_changes,
)
from agentproof.schema import Severity

DEMO_APP = str(Path(__file__).resolve().parent.parent / "demo-app")
TASK = "Fix password reset token handling"


def _demo_diffs():
    return parse_diff(DEMO_APP, "main", "ai-fix")


def test_auth_rule_detects_deleted_expiry_check():
    findings = auth.check(_demo_diffs())
    assert len(findings) >= 1
    assert all(f.severity == Severity.HIGH for f in findings)
    assert any("auth.py" in f.file_path for f in findings)
    assert any("is_expired" in f.evidence for f in findings)


def test_auth_rule_ignores_unrelated_deletions():
    file_diffs = [
        FileDiff(
            file_path="backend/utils.py",
            deleted_lines=[ChangedLine(line_number=3, content="    return value.strip()")],
        )
    ]
    assert auth.check(file_diffs) == []


def test_secrets_rule_detects_hardcoded_api_key():
    findings = secrets.check(_demo_diffs())
    assert len(findings) == 1
    finding = findings[0]
    assert finding.file_path == "backend/utils.py"
    assert finding.severity == Severity.CRITICAL
    assert "sk-1234secret" in finding.evidence


def test_secrets_rule_detects_generic_hardcoded_password():
    file_diffs = [
        FileDiff(
            file_path="backend/config.py",
            added_lines=[ChangedLine(line_number=10, content='password = "hunter2"')],
        )
    ]
    findings = secrets.check(file_diffs)
    assert len(findings) == 1
    assert findings[0].severity == Severity.HIGH


def test_secrets_rule_detects_json_style_quoted_key_api_key():
    file_diffs = [
        FileDiff(
            file_path="config/settings.json",
            added_lines=[ChangedLine(line_number=3, content='  "api_key": "sk-abcd1234efgh"')],
        )
    ]
    findings = secrets.check(file_diffs)
    assert len(findings) == 1
    assert findings[0].severity == Severity.CRITICAL
    assert findings[0].file_path == "config/settings.json"


def test_secrets_rule_detects_json_style_quoted_key_password():
    file_diffs = [
        FileDiff(
            file_path="config/settings.json",
            added_lines=[ChangedLine(line_number=4, content='  "password": "hunter2"')],
        )
    ]
    findings = secrets.check(file_diffs)
    assert len(findings) == 1
    assert findings[0].severity == Severity.HIGH


def test_secrets_rule_detects_yaml_style_unquoted_key():
    file_diffs = [
        FileDiff(
            file_path="config/settings.yaml",
            added_lines=[ChangedLine(line_number=2, content='secret: "s3cr3t-value"')],
        )
    ]
    findings = secrets.check(file_diffs)
    assert len(findings) == 1
    assert findings[0].severity == Severity.HIGH


def test_secrets_rule_ignores_unrelated_quoted_json_fields():
    file_diffs = [
        FileDiff(
            file_path="config/settings.json",
            added_lines=[ChangedLine(line_number=2, content='  "username": "admin"')],
        )
    ]
    assert secrets.check(file_diffs) == []


def test_logging_safety_flags_password_print():
    file_diffs = [
        FileDiff(
            file_path="backend/debug.py",
            added_lines=[ChangedLine(line_number=5, content='print(f"password={password}")')],
        )
    ]
    findings = logging_safety.check(file_diffs)
    assert len(findings) == 1
    assert findings[0].severity == Severity.HIGH


def test_logging_safety_flags_prompt_as_medium():
    file_diffs = [
        FileDiff(
            file_path="backend/debug.py",
            added_lines=[ChangedLine(line_number=5, content="logger.info(prompt)")],
        )
    ]
    findings = logging_safety.check(file_diffs)
    assert len(findings) == 1
    assert findings[0].severity == Severity.MEDIUM


def test_logging_safety_ignores_calls_without_sensitive_fields():
    file_diffs = [
        FileDiff(
            file_path="backend/debug.py",
            added_lines=[ChangedLine(line_number=5, content='print("startup complete")')],
        )
    ]
    assert logging_safety.check(file_diffs) == []


def test_logging_safety_flags_logging_module_high_risk_field():
    file_diffs = [
        FileDiff(
            file_path="backend/debug.py",
            added_lines=[ChangedLine(line_number=5, content='logging.info(f"token={token}")')],
        )
    ]
    findings = logging_safety.check(file_diffs)
    assert len(findings) == 1
    assert findings[0].severity == Severity.HIGH


def test_logging_safety_flags_logging_module_medium_risk_field():
    file_diffs = [
        FileDiff(
            file_path="backend/debug.py",
            added_lines=[ChangedLine(line_number=5, content="logging.warning(prompt)")],
        )
    ]
    findings = logging_safety.check(file_diffs)
    assert len(findings) == 1
    assert findings[0].severity == Severity.MEDIUM


def test_logging_safety_flags_logging_debug_and_error_levels():
    file_diffs = [
        FileDiff(
            file_path="backend/debug.py",
            added_lines=[
                ChangedLine(line_number=5, content='logging.debug(f"secret={secret}")'),
                ChangedLine(line_number=6, content='logging.error(f"api_key={api_key}")'),
            ],
        )
    ]
    findings = logging_safety.check(file_diffs)
    assert len(findings) == 2
    assert all(f.severity == Severity.HIGH for f in findings)


def test_logging_safety_ignores_logging_module_calls_without_sensitive_fields():
    file_diffs = [
        FileDiff(
            file_path="backend/debug.py",
            added_lines=[ChangedLine(line_number=5, content='logging.info("Starting up")')],
        )
    ]
    assert logging_safety.check(file_diffs) == []


def test_logging_safety_does_not_confuse_similarly_named_identifiers():
    file_diffs = [
        FileDiff(
            file_path="backend/debug.py",
            added_lines=[
                ChangedLine(line_number=5, content='logout_handler.info(f"token={token}")'),
                ChangedLine(line_number=6, content='logging_utils.info(f"token={token}")'),
            ],
        )
    ]
    assert logging_safety.check(file_diffs) == []


def test_test_coverage_rule_flags_missing_test_update():
    findings = test_coverage.check(_demo_diffs())
    assert len(findings) == 1
    assert findings[0].severity == Severity.MEDIUM
    assert "backend/auth.py" in findings[0].evidence
    assert "backend/utils.py" in findings[0].evidence


def test_test_coverage_rule_ignores_non_source_files():
    file_diffs = [
        FileDiff(file_path="README.md", added_lines=[ChangedLine(1, "# Demo App")]),
        FileDiff(file_path="about.txt", added_lines=[ChangedLine(1, "This file was created.")]),
    ]
    assert test_coverage.check(file_diffs) == []


def test_test_coverage_rule_still_flags_mixed_code_and_docs():
    file_diffs = [
        FileDiff(file_path="backend/auth.py", added_lines=[ChangedLine(1, "x = 1")]),
        FileDiff(file_path="README.md", added_lines=[ChangedLine(1, "# Demo App")]),
    ]
    findings = test_coverage.check(file_diffs)
    assert len(findings) == 1
    assert "backend/auth.py" in findings[0].evidence
    assert "README.md" not in findings[0].evidence


def test_test_coverage_rule_passes_when_tests_updated():
    file_diffs = [
        FileDiff(file_path="backend/auth.py", added_lines=[ChangedLine(1, "x = 1")]),
        FileDiff(file_path="tests/test_auth.py", added_lines=[ChangedLine(1, "def test_x(): ...")]),
    ]
    assert test_coverage.check(file_diffs) == []


def test_unrelated_changes_flags_utils_py_for_password_reset_task():
    findings = unrelated_changes.check(_demo_diffs(), task=TASK)
    flagged_paths = {f.file_path for f in findings}
    assert "backend/utils.py" in flagged_paths
    assert "backend/auth.py" not in flagged_paths
    assert all(f.severity == Severity.MEDIUM for f in findings)


def test_unrelated_changes_no_task_means_no_findings():
    assert unrelated_changes.check(_demo_diffs(), task=None) == []


def test_unrelated_changes_does_not_false_positive_on_substring_match():
    # "tokenizer" merely contains "token" as a substring — it should NOT be
    # treated as related to a task about password reset tokens.
    file_diffs = [
        FileDiff(
            file_path="nlp/tokenizer.py",
            added_lines=[ChangedLine(line_number=1, content="class Tokenizer: pass")],
        )
    ]
    findings = unrelated_changes.check(file_diffs, task=TASK)
    assert len(findings) == 1
    assert findings[0].file_path == "nlp/tokenizer.py"


def test_unrelated_changes_matches_plural_form_of_keyword():
    # "tokens" (plural) should still count as related to keyword "token".
    file_diffs = [
        FileDiff(
            file_path="backend/store.py",
            added_lines=[ChangedLine(line_number=1, content="reset_tokens = {}")],
        )
    ]
    assert unrelated_changes.check(file_diffs, task=TASK) == []


def test_unreviewable_changes_flags_binary_file():
    file_diffs = [FileDiff(file_path="assets/logo.png", is_binary=True)]
    findings = unreviewable_changes.check(file_diffs)
    assert len(findings) == 1
    assert findings[0].severity == Severity.MEDIUM
    assert findings[0].file_path == "assets/logo.png"


def test_unreviewable_changes_flags_pure_rename():
    file_diffs = [
        FileDiff(file_path="backend/utils_renamed.py", is_rename=True, old_path="backend/utils.py")
    ]
    findings = unreviewable_changes.check(file_diffs)
    assert len(findings) == 1
    assert findings[0].severity == Severity.LOW
    assert "backend/utils.py" in findings[0].evidence
    assert "backend/utils_renamed.py" in findings[0].evidence


def test_unreviewable_changes_ignores_rename_with_content_change():
    file_diffs = [
        FileDiff(
            file_path="backend/auth_handler.py",
            is_rename=True,
            old_path="backend/auth.py",
            deleted_lines=[ChangedLine(57, "    if is_expired(token):")],
        )
    ]
    assert unreviewable_changes.check(file_diffs) == []


def test_unreviewable_changes_ignores_normal_text_changes():
    assert unreviewable_changes.check(_demo_diffs()) == []
