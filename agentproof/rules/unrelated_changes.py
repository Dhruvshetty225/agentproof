"""Flag changed files that don't appear related to the stated task."""

from __future__ import annotations

import re

from agentproof.diff_parser import FileDiff
from agentproof.schema import Finding, Severity

RULE_ID = "SCOPE001"

_STOPWORDS = {
    "a",
    "an",
    "the",
    "to",
    "of",
    "for",
    "and",
    "or",
    "in",
    "on",
    "is",
    "are",
    "fix",
    "issue",
    "bug",
    "handling",
    "with",
}
_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_]+")


def _keywords(task: str) -> set[str]:
    words = {w.lower() for w in _WORD_RE.findall(task)}
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _file_text(file_diff: FileDiff) -> str:
    parts = [file_diff.file_path]
    parts.extend(line.content for line in file_diff.added_lines)
    parts.extend(line.content for line in file_diff.deleted_lines)
    return "\n".join(parts).lower()


def check(file_diffs: list[FileDiff], task: str | None = None) -> list[Finding]:
    if not task:
        return []

    keywords = _keywords(task)
    if not keywords:
        return []

    findings: list[Finding] = []
    for file_diff in file_diffs:
        text = _file_text(file_diff)
        if any(keyword in text for keyword in keywords):
            continue

        findings.append(
            Finding(
                rule_id=RULE_ID,
                severity=Severity.MEDIUM,
                title="Change appears unrelated to the stated task",
                file_path=file_diff.file_path,
                line_number=None,
                evidence=(
                    f"'{file_diff.file_path}' was modified but does not reference "
                    f"any of the task's keywords ({', '.join(sorted(keywords))})."
                ),
                recommendation=(
                    "Verify this file needed to change for the task "
                    f"'{task}'. Out-of-scope edits from an AI agent are a common "
                    "source of unreviewed side effects."
                ),
            )
        )
    return findings
