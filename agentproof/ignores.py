"""Inline ignore directives: ``agentproof: ignore[RULE_ID]``.

Exact rules:

* Syntax: ``agentproof: ignore[AUTH001]`` or ``agentproof: ignore[AUTH001, LOG001]``
  anywhere on a line, usually in a comment. "agentproof:" is lowercase; rule
  IDs are case-sensitive and look like AUTH001. Spaces around IDs are allowed.
* A directive only affects findings about the line that carries it.
* Added lines: the directive must be on the added line itself.
* Deleted lines: the directive must be on the deleted line itself, which means
  it was already in the base version. A change under review cannot silence a
  finding about code it deletes by adding a comment somewhere else.
* Findings without a line number (TESTCOV001, SCOPE001, UNREVIEWABLE001) cannot
  be ignored inline. Disable those rules in .agentproof.toml instead.
* A malformed directive has no effect: ``ignore``, ``ignore[]``,
  ``ignore[auth001]``, ``ignore[AUTH001,]``. A well-formed ID that is not a real
  rule simply matches nothing.
* Ignored findings are not scored, but the report still lists them.
* Ignores are applied before block grouping, line by line.
"""

from __future__ import annotations

import re

from agentproof.diff_parser import FileDiff
from agentproof.schema import DiffSide, Finding

_DIRECTIVE_RE = re.compile(r"agentproof:\s*ignore\[([^\]]*)\]")
_RULE_ID_RE = re.compile(r"[A-Z]+[0-9]+")


def ignored_rule_ids(content: str) -> set[str]:
    """Rule IDs named by well-formed ignore directives on this line."""
    rule_ids: set[str] = set()
    for match in _DIRECTIVE_RE.finditer(content):
        listed = [part.strip() for part in match.group(1).split(",")]
        if all(_RULE_ID_RE.fullmatch(rule_id) for rule_id in listed):
            rule_ids.update(listed)
    return rule_ids


def _line_content(finding: Finding, file_diffs: dict[str, FileDiff]) -> str | None:
    """The source line a finding points at, from the matching side of the diff."""
    file_diff = file_diffs.get(finding.file_path)
    if file_diff is None or finding.line_number is None:
        return None
    if finding.side is DiffSide.NEW:
        lines = file_diff.added_lines
    elif finding.side is DiffSide.OLD:
        lines = file_diff.deleted_lines
    else:
        return None
    for line in lines:
        if line.line_number == finding.line_number:
            return line.content
    return None


def split_ignored(
    findings: list[Finding], file_diffs: list[FileDiff]
) -> tuple[list[Finding], list[Finding]]:
    """Return (kept, ignored) according to the directives on each finding's line."""
    by_path = {f.file_path: f for f in file_diffs}
    kept: list[Finding] = []
    ignored: list[Finding] = []
    for finding in findings:
        content = _line_content(finding, by_path)
        if content is not None and finding.rule_id in ignored_rule_ids(content):
            ignored.append(finding)
        else:
            kept.append(finding)
    return kept, ignored
