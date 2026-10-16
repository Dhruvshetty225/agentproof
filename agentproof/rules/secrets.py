"""Detect hardcoded secrets, API keys, passwords, and tokens.

An added line is flagged when it contains either:

1. A credential-named field assigned a quoted literal, such as
   ``db_password = "..."`` or ``"api_key": "..."``. The field name must *end*
   with a credential word, so ``password_hash = "..."`` is not flagged.
   Environment lookups such as ``os.environ["DB_PASSWORD"]`` are not quoted
   literals, so they never match.
2. A value shaped like a known provider token (OpenAI-style ``sk-``, AWS,
   GitHub, Slack) or a PEM private-key header.

Each line produces at most one finding, even when several patterns match it.
"""

from __future__ import annotations

import re

from agentproof.diff_parser import ChangedLine, FileDiff
from agentproof.identifiers import ends_with_phrase, identifier_words
from agentproof.schema import Finding, Severity

RULE_ID = "SECRET001"

# A field name (optionally quoted, as in JSON/YAML), then ":" or "=", then a
# quoted value. Whether the field is a credential is decided separately.
_ASSIGNMENT_RE = re.compile(r"""["']?([A-Za-z_][\w-]*)["']?\s*[:=]\s*["']([^"']+)["']""")

# A field is a credential when its name ends with one of these word sequences:
# "db_password", "client_secret", "githubToken", "x-api-key", "SECRET_KEY".
_CREDENTIAL_SUFFIXES = [
    ("password",),
    ("secret",),
    ("token",),
    ("api", "key"),
    ("apikey",),
    ("secret", "key"),
]

# Token shapes are case-sensitive. The lookarounds stop a match from starting
# or ending in the middle of a longer run of letters and digits, so that
# "task-list" does not contain an "sk-" key.
_START = r"(?<![A-Za-z0-9])"
_END = r"(?![A-Za-z0-9])"
_TOKEN_PATTERNS = [
    ("API-key-shaped secret", re.compile(_START + r"sk-[A-Za-z0-9]{4,}")),
    ("AWS access key ID", re.compile(_START + r"AKIA[A-Z0-9]{16}" + _END)),
    ("GitHub token", re.compile(_START + r"gh[pos]_[A-Za-z0-9]{36}" + _END)),
    ("Slack token", re.compile(_START + r"xox[baprs]-[A-Za-z0-9][A-Za-z0-9-]*")),
    (
        "PEM private key",
        re.compile(r"-----BEGIN (?:(?:RSA|EC|OPENSSH|ENCRYPTED) )?PRIVATE KEY-----"),
    ),
]


def _credential_field(content: str) -> str | None:
    """Return the name of the first credential field assigned a quoted literal."""
    for match in _ASSIGNMENT_RE.finditer(content):
        field_name = match.group(1)
        words = identifier_words(field_name)
        if any(ends_with_phrase(words, suffix) for suffix in _CREDENTIAL_SUFFIXES):
            return field_name
    return None


def _token_kind(content: str) -> str | None:
    """Return the kind of the first known token shape found in `content`."""
    for kind, pattern in _TOKEN_PATTERNS:
        if pattern.search(content):
            return kind
    return None


def _check_line(file_path: str, line: ChangedLine) -> Finding | None:
    field_name = _credential_field(line.content)
    token_kind = _token_kind(line.content)
    if field_name is None and token_kind is None:
        return None

    if field_name is not None:
        title = "Hardcoded credential added to source code"
        recommendation = (
            f"Remove the hardcoded {field_name} and load it from an "
            "environment variable or secret manager instead."
        )
    else:
        title = f"{token_kind} added to source code"
        recommendation = (
            f"Remove this {token_kind}, revoke it if it was ever real, and "
            "load it from an environment variable or secret manager instead."
        )

    return Finding(
        rule_id=RULE_ID,
        severity=Severity.CRITICAL if token_kind else Severity.HIGH,
        title=title,
        file_path=file_path,
        line_number=line.line_number,
        evidence=line.content.strip(),
        recommendation=recommendation,
    )


def check(file_diffs: list[FileDiff], task: str | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for file_diff in file_diffs:
        for line in file_diff.added_lines:
            finding = _check_line(file_diff.file_path, line)
            if finding is not None:
                findings.append(finding)
    return findings
