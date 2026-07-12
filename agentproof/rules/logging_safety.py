"""Detect unsafe logging or printing of sensitive values."""

from __future__ import annotations

import re

from agentproof.diff_parser import FileDiff
from agentproof.schema import Finding, Severity

RULE_ID = "LOG001"

_LOG_CALL_RE = re.compile(r"(?i)\b(print|log(?:ging|ger)?\.\w+)\s*\(")

_HIGH_RISK_FIELDS = ["password", "token", "secret", "api_key"]
_MEDIUM_RISK_FIELDS = ["prompt", "user_message"]
_ALL_FIELDS = _HIGH_RISK_FIELDS + _MEDIUM_RISK_FIELDS
_FIELD_RE = re.compile(r"(?i)\b(" + "|".join(_ALL_FIELDS) + r")\b")


def check(file_diffs: list[FileDiff], task: str | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for file_diff in file_diffs:
        for line in file_diff.added_lines:
            content = line.content
            if not _LOG_CALL_RE.search(content):
                continue

            field_match = _FIELD_RE.search(content)
            if not field_match:
                continue

            field = field_match.group(1).lower()
            severity = Severity.HIGH if field in _HIGH_RISK_FIELDS else Severity.MEDIUM

            findings.append(
                Finding(
                    rule_id=RULE_ID,
                    severity=severity,
                    title="Sensitive value may be logged or printed",
                    file_path=file_diff.file_path,
                    line_number=line.line_number,
                    evidence=content.strip(),
                    recommendation=(
                        f"Avoid logging or printing '{field}' directly. Redact or "
                        "omit sensitive fields before writing to logs or stdout."
                    ),
                )
            )
    return findings
