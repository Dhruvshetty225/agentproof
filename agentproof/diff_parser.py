"""Parse the git diff between two branches into structured changes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from git import Repo

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_BINARY_HEADER_RE = re.compile(r"^Binary files (.+) and (.+) differ$")


@dataclass
class ChangedLine:
    """A single added or deleted line, with its line number in the relevant file."""

    line_number: int
    content: str


@dataclass
class FileDiff:
    """All changes made to a single file between base and branch."""

    file_path: str
    added_lines: list[ChangedLine] = field(default_factory=list)
    deleted_lines: list[ChangedLine] = field(default_factory=list)
    is_binary: bool = False
    is_rename: bool = False
    old_path: str | None = None

    @property
    def is_pure_rename(self) -> bool:
        """A rename with no accompanying line changes (nothing to review as text)."""
        return self.is_rename and not self.added_lines and not self.deleted_lines

    @property
    def is_test_file(self) -> bool:
        name = self.file_path.rsplit("/", 1)[-1]
        return (
            "test" in self.file_path.lower().split("/")
            or name.startswith("test_")
            or name.endswith("_test.py")
        )


def _file_path_from_header(minus_path: str, plus_path: str) -> str:
    """Pick the most meaningful path out of a diff's --- / +++ headers."""
    if plus_path != "/dev/null":
        return plus_path[2:] if plus_path.startswith(("a/", "b/")) else plus_path
    if minus_path != "/dev/null":
        return minus_path[2:] if minus_path.startswith(("a/", "b/")) else minus_path
    return plus_path


def parse_diff(repo_path: str, base: str, branch: str) -> list[FileDiff]:
    """Parse the diff between `base` and `branch` in the repo at `repo_path`.

    Returns one FileDiff per changed file, containing added and deleted
    lines along with their line numbers (new-file numbers for additions,
    old-file numbers for deletions).
    """
    repo = Repo(repo_path)
    diff_text = repo.git.diff(base, branch, "-U0", "--no-color")
    return _parse_unified_diff(diff_text)


def _parse_unified_diff(diff_text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    current: FileDiff | None = None
    old_line = 0
    new_line = 0
    minus_path = ""
    plus_path = ""
    rename_from: str | None = None

    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            if current is not None:
                files.append(current)
            current = None
            minus_path = ""
            plus_path = ""
            rename_from = None
        elif line.startswith("rename from "):
            rename_from = line[len("rename from ") :].strip()
        elif line.startswith("rename to "):
            rename_to = line[len("rename to ") :].strip()
            current = FileDiff(file_path=rename_to, is_rename=True, old_path=rename_from)
        elif line.startswith("Binary files ") and line.endswith(" differ"):
            match = _BINARY_HEADER_RE.match(line)
            if match and current is None:
                current = FileDiff(
                    file_path=_file_path_from_header(match.group(1), match.group(2)),
                    is_binary=True,
                )
        elif line.startswith("--- "):
            minus_path = line[4:].strip()
        elif line.startswith("+++ "):
            plus_path = line[4:].strip()
            if current is None:
                current = FileDiff(file_path=_file_path_from_header(minus_path, plus_path))
        elif line.startswith("@@"):
            match = _HUNK_HEADER_RE.match(line)
            if match:
                old_line = int(match.group(1))
                new_line = int(match.group(2))
        elif current is not None and line.startswith("-") and not line.startswith("---"):
            current.deleted_lines.append(ChangedLine(line_number=old_line, content=line[1:]))
            old_line += 1
        elif current is not None and line.startswith("+") and not line.startswith("+++"):
            current.added_lines.append(ChangedLine(line_number=new_line, content=line[1:]))
            new_line += 1

    if current is not None:
        files.append(current)

    return files


def changed_file_paths(file_diffs: list[FileDiff]) -> list[str]:
    return [f.file_path for f in file_diffs]
