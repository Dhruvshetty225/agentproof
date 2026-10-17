"""SECRET001: hardcoded credentials and token-shaped secrets.

Every token below is fabricated. Token-shaped values are built by string
concatenation (for example "AKIA" + "X" * 16) so this file never contains a
literal that looks like a real credential to a secret scanner, including
AgentProof itself.
"""

import pytest

from agentproof.diff_parser import ChangedLine, FileDiff
from agentproof.rules import secrets
from agentproof.schema import Severity

FAKE_AWS_KEY_ID = "AKIA" + "X" * 16
FAKE_GITHUB_TOKEN = "ghp_" + "x" * 36
FAKE_SLACK_TOKEN = "xoxb-" + "0000-fake"


def _added(content: str) -> list[FileDiff]:
    return [FileDiff(file_path="app/config.py", added_lines=[ChangedLine(7, content)])]


# --- compound credential names -------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        'db_password = "hunter2"',
        'DB_PASSWORD = "hunter2"',
        'dbPassword = "hunter2";',
        'client_secret: "not-a-real-secret"',
        '"github_token": "fake-value"',
        'const apiKey = "fake-value";',
        'x-api-key: "fake-value"',
        'SECRET_KEY = "django-insecure-fake"',
        # Pre-existing forms that must keep working.
        'password = "hunter2"',
        '  "password": "hunter2"',
        'secret: "s3cr3t-value"',
        'token = "fake-value"',
    ],
)
def test_flags_credential_named_field_assigned_a_literal(content):
    findings = secrets.check(_added(content))
    assert len(findings) == 1
    assert findings[0].severity == Severity.HIGH
    assert findings[0].title == "Hardcoded credential added to source code"
    assert findings[0].line_number == 7


@pytest.mark.parametrize(
    "content",
    [
        # The credential word is not the last word of the name.
        'password_hash = "pbkdf2$fake"',
        'token_type = "Bearer"',
        'secret_name = "prod/db"',
        'passwordless_login = "enabled"',
        'max_tokens = "4096"',
        # Unrelated fields.
        'author = "Jane"',
        '  "username": "admin"',
        # Comparisons are not assignments.
        'if password == "hunter2":',
        # Environment-variable lookups are not hardcoded literals.
        'password = os.environ["DB_PASSWORD"]',
        'token = os.getenv("GITHUB_TOKEN")',
        'api_key = os.environ.get("API_KEY", None)',
        "const apiKey = process.env.API_KEY;",
        "db_password: ${DB_PASSWORD}",
    ],
)
def test_ignores_non_credentials_and_environment_lookups(content):
    assert secrets.check(_added(content)) == []


# --- token shapes ---------------------------------------------------------


@pytest.mark.parametrize(
    "content, kind",
    [
        (f'aws_id = "{FAKE_AWS_KEY_ID}"', "AWS access key ID"),
        (f"export AWS_ACCESS_KEY_ID={FAKE_AWS_KEY_ID}", "AWS access key ID"),
        (f'gh = "{FAKE_GITHUB_TOKEN}"', "GitHub token"),
        (f'gh = "{"gho_" + "A1" * 18}"', "GitHub token"),
        (f'gh = "{"ghs_" + "Z9" * 18}"', "GitHub token"),
        (f'hook = "{FAKE_SLACK_TOKEN}"', "Slack token"),
        (f'hook = "{"xoxp-" + "1"}"', "Slack token"),
        ("-----BEGIN " + "PRIVATE KEY-----", "PEM private key"),
        ("-----BEGIN " + "RSA PRIVATE KEY-----", "PEM private key"),
        ("-----BEGIN " + "EC PRIVATE KEY-----", "PEM private key"),
        ("-----BEGIN " + "OPENSSH PRIVATE KEY-----", "PEM private key"),
        ("-----BEGIN " + "ENCRYPTED PRIVATE KEY-----", "PEM private key"),
        (f'key = "{"sk-" + "abcd1234"}"', "API-key-shaped secret"),
    ],
)
def test_flags_known_token_shapes_as_critical(content, kind):
    findings = secrets.check(_added(content))
    assert len(findings) == 1
    assert findings[0].severity == Severity.CRITICAL
    assert findings[0].title == f"{kind} added to source code"


@pytest.mark.parametrize(
    "content",
    [
        # Wrong lengths.
        f'x = "{"AKIA" + "X" * 15}"',
        f'x = "{"AKIA" + "X" * 17}"',
        f'x = "{"ghp_" + "x" * 35}"',
        f'x = "{"ghp_" + "x" * 37}"',
        # Wrong alphabet or prefix.
        f'x = "{"AKIA" + "x" * 16}"',
        f'x = "{"akia" + "X" * 16}"',
        f'x = "{"ghx_" + "x" * 36}"',
        f'x = "{"ghp_" + "x" * 35 + "!"}"',
        f'x = "{"xoxz-" + "123"}"',
        # Slack prefix with an empty body.
        'x = "xoxb-"',
        # Token glued to surrounding letters or digits (boundaries).
        f'x = "{"Z" + FAKE_AWS_KEY_ID}"',
        f'x = "{"1" + FAKE_GITHUB_TOKEN}"',
        f'x = "{"a" + FAKE_SLACK_TOKEN}"',
        'css_class = "task-list"',
        'label = "risk-high1"',
        # Public material is not a private key.
        "-----BEGIN " + "PUBLIC KEY-----",
        "-----BEGIN " + "RSA PUBLIC KEY-----",
        "-----BEGIN " + "CERTIFICATE-----",
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFake user@host",
    ],
)
def test_ignores_malformed_or_public_shapes(content):
    assert secrets.check(_added(content)) == []


def test_hyphenated_sk_key_is_flagged_and_its_value_is_the_whole_key():
    key = "sk-" + "proj-" + "Abc123Def456_Ghi789-Jkl012"
    content = f"OPENAI_API_KEY={key}"
    findings = secrets.check(_added(content))
    assert len(findings) == 1
    assert findings[0].title == "API-key-shaped secret added to source code"
    # Redaction masks exactly these values, so the whole key must be one value.
    assert secrets.secret_values(content) == [key]


# --- one finding per line ---------------------------------------------------


def test_assignment_and_token_shape_on_one_line_give_one_critical_finding():
    findings = secrets.check(_added(f'aws_secret_token = "{FAKE_AWS_KEY_ID}"'))
    assert len(findings) == 1
    assert findings[0].severity == Severity.CRITICAL
    assert findings[0].title == "Hardcoded credential added to source code"
    assert "aws_secret_token" in findings[0].recommendation


def test_two_token_shapes_on_one_line_give_one_finding():
    findings = secrets.check(_added(f'pair = ("{FAKE_AWS_KEY_ID}", "{FAKE_GITHUB_TOKEN}")'))
    assert len(findings) == 1
    assert findings[0].severity == Severity.CRITICAL


def test_separate_lines_give_separate_findings():
    file_diffs = [
        FileDiff(
            file_path="app/config.py",
            added_lines=[
                ChangedLine(1, f'aws_id = "{FAKE_AWS_KEY_ID}"'),
                ChangedLine(2, 'db_password = "hunter2"'),
            ],
        )
    ]
    findings = secrets.check(file_diffs)
    assert [f.line_number for f in findings] == [1, 2]


def test_deleted_secrets_are_not_flagged():
    file_diffs = [
        FileDiff(file_path="app/config.py", deleted_lines=[ChangedLine(3, 'db_password = "hunter2"')])
    ]
    assert secrets.check(file_diffs) == []
