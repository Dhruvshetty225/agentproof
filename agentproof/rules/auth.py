"""Detect removed authentication/authorization safeguards.

A deleted line is flagged when one of the names on it refers to a security
check. Names are compared word by word (see agentproof.identifiers), so
"is_authorized" and "isAuthorized" both match "authorized", while unrelated
names such as "author" or "tokenizer" do not. Decorators are ordinary lines,
so "@login_required" and "@require_role('admin')" are covered by the same
matching. Lines that are only a comment are skipped.
"""

from __future__ import annotations

from agentproof.diff_parser import FileDiff
from agentproof.identifiers import contains_phrase, identifier_words, identifiers_in
from agentproof.schema import DiffSide, Finding, Severity

RULE_ID = "AUTH001"

# A name is security-related if any of its words is one of these,
# e.g. "check_permission", "verifyToken", "csrf_protect", "is_expired".
_SECURITY_WORDS = {
    "auth",
    "authorize",
    "authorized",
    "authorization",
    "authenticate",
    "authenticated",
    "authentication",
    "verify",
    "permission",
    "permissions",
    "csrf",
    "expiry",
    "expired",
}

# Words that are too common to match alone ("login", "admin", "role") only
# count when they appear together, in order, inside one name.
_SECURITY_PHRASES = [
    ("login", "required"),
    ("has", "access"),
    ("is", "admin"),
    ("require", "role"),
    ("expires", "at"),
]

# "token" only matches as a whole name, as it did before word splitting.
# Inside longer names it is usually unrelated to security, e.g. "token_count"
# or "next_page_token".
_STANDALONE_WORDS = {"token"}

_COMMENT_PREFIXES = ("#", "//", "/*", "*/", "* ")


def _is_comment_only(content: str) -> bool:
    stripped = content.strip()
    return stripped == "*" or stripped.startswith(_COMMENT_PREFIXES)


def _is_security_name(name: str) -> bool:
    if name.lower() in _STANDALONE_WORDS:
        return True
    words = identifier_words(name)
    if any(word in _SECURITY_WORDS for word in words):
        return True
    return any(contains_phrase(words, phrase) for phrase in _SECURITY_PHRASES)


def _is_security_line(content: str) -> bool:
    if _is_comment_only(content):
        return False
    return any(_is_security_name(name) for name in identifiers_in(content))


def check(file_diffs: list[FileDiff], task: str | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for file_diff in file_diffs:
        for line in file_diff.deleted_lines:
            if _is_security_line(line.content):
                findings.append(
                    Finding(
                        rule_id=RULE_ID,
                        severity=Severity.HIGH,
                        title="Security-relevant code was deleted",
                        file_path=file_diff.file_path,
                        line_number=line.line_number,
                        evidence=line.content.strip(),
                        side=DiffSide.OLD,
                        recommendation=(
                            "Confirm this deletion is intentional. Removing auth, "
                            "verification, permission, or token-expiry checks can "
                            "silently reintroduce a security vulnerability."
                        ),
                    )
                )
    return findings
