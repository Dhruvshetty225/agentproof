"""LOG001: sensitive values passed to print/logging calls."""

import pytest

from agentproof.diff_parser import ChangedLine, FileDiff
from agentproof.rules import logging_safety
from agentproof.schema import Severity


def _added(content: str) -> list[FileDiff]:
    return [FileDiff(file_path="app/service.py", added_lines=[ChangedLine(12, content)])]


@pytest.mark.parametrize(
    "content, name",
    [
        # Passed directly.
        ("logger.info(token)", "token"),
        ("print(password)", "password"),
        ("logger.info(access_token)", "access_token"),
        ("print(db_password)", "db_password"),
        ("logging.debug(user.apiKey)", "apiKey"),
        # Through f-strings, including attributes and format specs.
        ('logger.info(f"token={token}")', "token"),
        ('logger.debug(f"Got token {resp.access_token}")', "access_token"),
        ('print(f"{secret!r:>10}")', "secret"),
        ('logger.info(rf"raw {password}")', "password"),
        # Through concatenation, .format() and % formatting.
        ('logger.info("token: " + token)', "token"),
        ('logger.info("token: {}".format(token))', "token"),
        ('logger.info("token: %s" % token)', "token"),
        # As an additional logging argument.
        ('logger.info("token: %s", token)', "token"),
        ('logger.warning("login failed for %s with %s", user, password)', "password"),
        # Through quoted lookup keys, which name a value rather than a message.
        ('logger.info(data["password"])', "password"),
        ("logger.info(request.args.get('token'))", "token"),
        ('print(os.getenv("API_TOKEN"))', "API_TOKEN"),
        ('logger.info("login", extra={"password": pw})', "password"),
        ('logger.info(f"{creds[\'secret\']}")', "secret"),
        # JavaScript-style template literal placeholders.
        ("logger.info(`token=${token}`)", "token"),
    ],
)
def test_flags_sensitive_values_as_high(content, name):
    findings = logging_safety.check(_added(content))
    assert len(findings) == 1
    assert findings[0].severity == Severity.HIGH
    assert f"'{name}'" in findings[0].recommendation


@pytest.mark.parametrize(
    "content",
    [
        "logger.info(system_prompt)",
        'logger.debug(f"user said {last_user_message}")',
    ],
)
def test_flags_prompts_and_user_messages_as_medium(content):
    findings = logging_safety.check(_added(content))
    assert len(findings) == 1
    assert findings[0].severity == Severity.MEDIUM


def test_most_severe_name_on_the_line_wins():
    findings = logging_safety.check(_added("logger.info(prompt, token)"))
    assert len(findings) == 1
    assert findings[0].severity == Severity.HIGH
    assert "'token'" in findings[0].recommendation


@pytest.mark.parametrize(
    "content",
    [
        # Sensitive words only inside a static message.
        'logger.info("Reset token sent")',
        "print('Password updated')",
        'logger.info(f"Reset token sent to {user.email}")',
        'logger.info("Token for %s refreshed", user.id)',
        'logger.info("Password: %s", "<redacted>")',
        'logger.info(f"{{token}} is shown with literal braces")',
        "logger.info(`token refreshed for ${user.id}`)",
        # The sensitive word is not the last word of the name.
        "logger.info(token_count)",
        "logger.debug(prompt_tokens)",
        "print(password_hash_algorithm)",
        # The sensitive name appears before the call, not in its arguments.
        'if token: logger.info("Reset token sent")',
        # Calls that are not print/logging.
        "send_email(user, token)",
        'logout_handler.info(f"token={token}")',
    ],
)
def test_ignores_static_messages_and_non_sensitive_names(content):
    assert logging_safety.check(_added(content)) == []
