"""Detect hardcoded secrets, API keys, passwords, and tokens."""

from __future__ import annotations

import re

from agentproof.diff_parser import FileDiff
from agentproof.schema import Finding, Severity

RULE_ID = "SECRET001"

_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api_key|password|secret|token)\s*[:=]\s*[\"']([^\"']+)[\"']"
)
_FAKE_KEY_RE = re.compile(r"sk-[A-Za-z0-9]{4,}")


def check(file_diffs: list[FileDiff], task: str | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for file_diff in file_diffs:
        for line in file_diff.added_lines:
            content = line.content

            match = _ASSIGNMENT_RE.search(content)
            if match:
                field_name, value = match.group(1), match.group(2)
                is_fake_key = bool(_FAKE_KEY_RE.search(value))
                findings.append(
                    Finding(
                        rule_id=RULE_ID,
                        severity=Severity.CRITICAL if is_fake_key else Severity.HIGH,
                        title="Hardcoded credential added to source code",
                        file_path=file_diff.file_path,
                        line_number=line.line_number,
                        evidence=content.strip(),
                        recommendation=(
                            f"Remove the hardcoded {field_name} and load it from an "
                            "environment variable or secret manager instead."
                        ),
                    )
                )
                continue

            key_match = _FAKE_KEY_RE.search(content)
            if key_match:
                findings.append(
                    Finding(
                        rule_id=RULE_ID,
                        severity=Severity.CRITICAL,
                        title="API-key-shaped secret added to source code",
                        file_path=file_diff.file_path,
                        line_number=line.line_number,
                        evidence=content.strip(),
                        recommendation=(
                            "Remove the hardcoded API key and load it from an "
                            "environment variable or secret manager instead."
                        ),
                    )
                )
    return findings
