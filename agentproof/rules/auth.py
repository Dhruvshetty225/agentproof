"""Detect removed authentication/authorization safeguards."""

from __future__ import annotations

import re

from agentproof.diff_parser import FileDiff
from agentproof.schema import Finding, Severity

RULE_ID = "AUTH001"

_KEYWORDS = [
    "auth",
    "verify",
    "permission",
    "token",
    "expiry",
    "expired",
    "is_expired",
    "expires_at",
]
_KEYWORD_RE = re.compile(r"(?i)\b(" + "|".join(re.escape(k) for k in _KEYWORDS) + r")\b")


def check(file_diffs: list[FileDiff], task: str | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for file_diff in file_diffs:
        for line in file_diff.deleted_lines:
            if _KEYWORD_RE.search(line.content):
                findings.append(
                    Finding(
                        rule_id=RULE_ID,
                        severity=Severity.HIGH,
                        title="Security-relevant code was deleted",
                        file_path=file_diff.file_path,
                        line_number=line.line_number,
                        evidence=line.content.strip(),
                        recommendation=(
                            "Confirm this deletion is intentional. Removing auth, "
                            "verification, permission, or token-expiry checks can "
                            "silently reintroduce a security vulnerability."
                        ),
                    )
                )
    return findings
