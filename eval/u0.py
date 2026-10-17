"""Convert a unified diff with context lines into git's zero-context form.

AgentProof always asks git for ``git diff -U0`` (no context lines), and its
parser is written for that format. The evaluation diffs have context: GitHub
compare diffs and the synthetic generator both use git's default of three
lines. ``to_u0`` rewrites such a diff into what ``git diff -U0`` would print,
so every AgentProof version is evaluated on the input format it was built for.

What changes:

- context lines are dropped;
- a hunk is split wherever context separated two groups of changes;
- each new hunk header ``@@ -a,b +c,d @@`` is recomputed with git's
  conventions: a count of 1 is left out, and a side with 0 lines starts at
  the line before the change.

What is kept as it is: file headers, binary and rename sections, and each
``\\ No newline at end of file`` marker that follows a changed line. The
optional function-name text git prints after a hunk header is dropped;
AgentProof's parser does not use it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class _Run:
    """One group of changed lines with no context line between them."""

    old_start: int  # old line number of the first line this run touches
    new_start: int
    lines: list[str] = field(default_factory=list)
    old_count: int = 0
    new_count: int = 0


def _range(start: int, count: int) -> str:
    if count == 1:
        return str(start)
    # A side with no lines points at the line *before* the change.
    return f"{start - 1 if count == 0 else start},{count}"


def _format_run(run: _Run) -> list[str]:
    header = f"@@ -{_range(run.old_start, run.old_count)} +{_range(run.new_start, run.new_count)} @@"
    return [header, *run.lines]


def _convert_hunk(header: str, body: list[str]) -> list[str]:
    """Turn one hunk (header plus body lines) into zero-context hunks."""
    match = _HUNK_HEADER_RE.match(header)
    if not match:
        raise ValueError(f"not a hunk header: {header!r}")
    old_start, old_count, new_start, new_count = (
        int(value) if value is not None else 1 for value in match.groups()
    )
    # The next old/new line numbers to be read. A side with 0 lines names the
    # line before the hunk, so the next line is one further on.
    old_line = old_start if old_count else old_start + 1
    new_line = new_start if new_count else new_start + 1

    output: list[str] = []
    run: _Run | None = None
    previous_kind = ""
    for line in body:
        kind = line[:1]
        if kind == " ":
            if run is not None:
                output.extend(_format_run(run))
                run = None
            old_line += 1
            new_line += 1
        elif kind in ("-", "+"):
            if run is None:
                run = _Run(old_start=old_line, new_start=new_line)
            run.lines.append(line)
            if kind == "-":
                run.old_count += 1
                old_line += 1
            else:
                run.new_count += 1
                new_line += 1
        elif kind == "\\":
            # "\ No newline at end of file" belongs to the line before it.
            # Keep it only if that line was a change.
            if previous_kind in ("-", "+") and run is not None:
                run.lines.append(line)
        else:
            raise ValueError(f"unexpected line inside a hunk: {line!r}")
        previous_kind = kind
    if run is not None:
        output.extend(_format_run(run))
    return output


def _hunk_length(header: str) -> tuple[int, int]:
    """The number of old and new lines a hunk header says its body covers."""
    match = _HUNK_HEADER_RE.match(header)
    if not match:
        raise ValueError(f"not a hunk header: {header!r}")
    _, old_count, _, new_count = match.groups()
    return (int(old_count) if old_count is not None else 1,
            int(new_count) if new_count is not None else 1)


def to_u0(diff_text: str) -> str:
    """Return ``diff_text`` rewritten as ``git diff -U0`` would print it."""
    lines = diff_text.split("\n")
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith("@@"):
            output.append(line)
            index += 1
            continue
        # A hunk body ends once it has covered the counts in its header,
        # plus any "\ No newline" marker right after the last line.
        old_left, new_left = _hunk_length(line)
        body: list[str] = []
        index += 1
        while index < len(lines) and (old_left > 0 or new_left > 0 or lines[index].startswith("\\")):
            body_line = lines[index]
            kind = body_line[:1]
            if kind in (" ", "-"):
                old_left -= 1
            if kind in (" ", "+"):
                new_left -= 1
            if kind not in (" ", "-", "+", "\\"):
                raise ValueError(f"hunk ended early at line {index + 1}: {body_line!r}")
            body.append(body_line)
            index += 1
        if old_left != 0 or new_left != 0:
            raise ValueError(f"hunk body does not match its header: {line!r}")
        output.extend(_convert_hunk(line, body))
    return "\n".join(output)


def changed_lines(diff_text: str) -> list[str]:
    """Every added or deleted line inside hunks, in order (for checking a conversion)."""
    result: list[str] = []
    in_hunk = False
    for line in diff_text.split("\n"):
        if line.startswith("diff --git"):
            in_hunk = False
        elif line.startswith("@@"):
            in_hunk = True
        elif in_hunk and line[:1] in ("-", "+"):
            result.append(line)
    return result


def check_u0(converted: str) -> None:
    """Raise ValueError unless every hunk header's counts match its lines and
    hunks within a file are in order without overlapping."""
    old_end = new_end = 0
    header: tuple[int, int, int, int] | None = None
    seen_old = seen_new = 0

    def finish() -> None:
        if header is not None and (seen_old, seen_new) != (header[1], header[3]):
            raise ValueError(f"hunk counts {header} do not match its lines ({seen_old}, {seen_new})")

    for line in converted.split("\n"):
        if line.startswith("diff --git"):
            finish()
            header = None
            old_end = new_end = 0
        elif line.startswith("@@"):
            finish()
            match = _HUNK_HEADER_RE.match(line)
            if not match:
                raise ValueError(f"not a hunk header: {line!r}")
            old_start, old_count, new_start, new_count = (
                int(value) if value is not None else 1 for value in match.groups()
            )
            if line[match.end():].strip():
                raise ValueError(f"unexpected text after hunk header: {line!r}")
            first_old = old_start if old_count else old_start + 1
            first_new = new_start if new_count else new_start + 1
            if first_old <= old_end or first_new <= new_end:
                raise ValueError(f"hunk overlaps or is out of order: {line!r}")
            old_end = first_old + old_count - 1
            new_end = first_new + new_count - 1
            header = (old_start, old_count, new_start, new_count)
            seen_old = seen_new = 0
        elif header is not None and line.startswith("-"):
            seen_old += 1
        elif header is not None and line.startswith("+"):
            seen_new += 1
        elif header is not None and line.startswith(" "):
            raise ValueError(f"context line left in converted diff: {line!r}")
    finish()
