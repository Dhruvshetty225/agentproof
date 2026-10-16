"""Merge findings that come from one deleted block of code.

When a whole ``if`` statement is deleted, a line-based rule such as AUTH001
flags both the condition and its body:

    -    if is_expired(token):                          <- flagged
    -        raise ValueError("reset token has expired") <- flagged

Both lines describe one removed safeguard, so they become one finding and are
scored once.

How a group is formed, per rule and per file, using deleted lines only:

* A flagged deleted line opens a group.
* The following deleted lines belong to that group while they are contiguous
  (no unchanged line in between) and indented *deeper* than the line that
  opened the group, i.e. the statement's body or continuation lines.
* A line at the same or a shallower indentation is a new statement and ends
  the group. Two adjacent but independent checks therefore stay separate.
* Blank lines neither open nor end a group.
"""

from __future__ import annotations

from dataclasses import replace

from agentproof.diff_parser import ChangedLine, FileDiff
from agentproof.schema import DiffSide, Finding, Severity

_SEVERITY_RANK = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]


def _indentation(content: str) -> int:
    return len(content) - len(content.lstrip())


def block_groups(deleted_lines: list[ChangedLine], flagged: set[int]) -> list[list[int]]:
    """Split the flagged deleted line numbers into one group per removed statement."""
    groups: list[list[int]] = []
    group_indent: int | None = None  # indentation of the line that opened the group
    previous_number: int | None = None

    for line in deleted_lines:
        contiguous = previous_number is not None and line.line_number == previous_number + 1
        previous_number = line.line_number
        if not line.content.strip():
            continue

        indent = _indentation(line.content)
        if group_indent is not None and not (contiguous and indent > group_indent):
            group_indent = None  # the opening statement's block has ended

        if line.line_number not in flagged:
            continue
        if group_indent is None:
            groups.append([line.line_number])
            group_indent = indent
        else:
            groups[-1].append(line.line_number)
    return groups


def _merge(members: list[Finding]) -> Finding:
    """Combine one group's findings: first location, all evidence, worst severity."""
    if len(members) == 1:
        return members[0]
    return replace(
        members[0],
        severity=max((m.severity for m in members), key=_SEVERITY_RANK.index),
        evidence="\n".join(m.evidence for m in members),
        end_line_number=members[-1].line_number,
    )


def group_deleted_blocks(findings: list[Finding], file_diffs: list[FileDiff]) -> list[Finding]:
    """Merge deleted-line findings of the same rule that share a removed block.

    Findings on added lines, or without a line, are returned unchanged. The
    original order is kept; a merged finding takes its first member's place.
    """
    deleted_lines = {f.file_path: f.deleted_lines for f in file_diffs}

    by_rule_and_file: dict[tuple[str, str], dict[int, Finding]] = {}
    for finding in findings:
        if finding.side is DiffSide.OLD and finding.line_number is not None:
            key = (finding.rule_id, finding.file_path)
            by_rule_and_file.setdefault(key, {})[finding.line_number] = finding

    # Maps each grouped finding to its merged replacement, or to None when it
    # was folded into an earlier finding of the same group.
    replacements: dict[Finding, Finding | None] = {}
    for (_rule_id, file_path), by_line in by_rule_and_file.items():
        for group in block_groups(deleted_lines.get(file_path, []), set(by_line)):
            members = [by_line[number] for number in group]
            replacements[members[0]] = _merge(members)
            for member in members[1:]:
                replacements[member] = None

    result = []
    for finding in findings:
        replacement = replacements.get(finding, finding)
        if replacement is not None:
            result.append(replacement)
    return result
