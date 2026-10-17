"""Parse the git diff between two branches into structured changes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from git import Repo

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_BINARY_HEADER_RE = re.compile(r"^Binary files (.+) and (.+) differ$")

_TEST_DIRECTORY_NAMES = {"test", "tests"}
_TEST_FILE_SUFFIXES = (
    "_test.py",
    ".test.js",
    ".test.ts",
    ".spec.js",
    ".spec.ts",
    "_test.go",
)


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
        """True if the path follows a common test-file naming convention.

        This looks only at the file's path. It does not measure what, or how
        much, the tests actually cover.
        """
        parts = self.file_path.split("/")
        name = parts[-1]
        lower_name = name.lower()
        return (
            any(part.lower() in _TEST_DIRECTORY_NAMES for part in parts)
            or lower_name.startswith("test_")
            or lower_name == "conftest.py"
            or lower_name.endswith(_TEST_FILE_SUFFIXES)
            # Case-sensitive on purpose: "FooTest.java" is a test, "Latest.java" is not.
            or name.endswith("Test.java")
        )


def _file_path_from_header(minus_path: str, plus_path: str) -> str:
    """Pick the most meaningful path out of a diff's --- / +++ headers."""
    if plus_path != "/dev/null":
        return plus_path[2:] if plus_path.startswith(("a/", "b/")) else plus_path
    if minus_path != "/dev/null":
        return minus_path[2:] if minus_path.startswith(("a/", "b/")) else minus_path
    return plus_path


def parse_diff(repo_path: str, base: str, branch: str) -> list[FileDiff]:
    """Parse the changes made on `branch` since it diverged from `base`.

    This is git's three-dot diff (``base...branch``): it compares `branch`
    with the merge base of the two refs, the same view as a pull request's
    "Files changed" tab. Commits added to `base` after the branch was created
    are therefore not shown as reversed changes. It needs enough history to
    find the merge base (in CI, check out with full history).

    Returns one FileDiff per changed file, containing added and deleted
    lines along with their line numbers (new-file numbers for additions,
    old-file numbers for deletions).
    """
    repo = Repo(repo_path)
    diff_text = repo.git.diff(f"{base}...{branch}", "-U0", "--no-color")
    return _parse_unified_diff(diff_text)


def _parse_unified_diff(diff_text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    current: FileDiff | None = None
    old_line = 0
    new_line = 0
    minus_path = ""
    plus_path = ""
    rename_from: str | None = None
    # File headers ("--- a/x", "+++ b/x", "rename ...") only appear before a
    # file's first hunk. Inside a hunk, "--- x" is a deleted line whose
    # content starts with "-- " (an SQL comment, a YAML "---" separator...).
    in_hunk = False

    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            if current is not None:
                files.append(current)
            current = None
            minus_path = ""
            plus_path = ""
            rename_from = None
            in_hunk = False
        elif line.startswith("@@"):
            match = _HUNK_HEADER_RE.match(line)
            if match:
                in_hunk = True
                old_line = int(match.group(1))
                new_line = int(match.group(2))
        elif not in_hunk:
            if line.startswith("rename from "):
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
        elif current is not None and line.startswith("-"):
            current.deleted_lines.append(ChangedLine(line_number=old_line, content=line[1:]))
            old_line += 1
        elif current is not None and line.startswith("+"):
            current.added_lines.append(ChangedLine(line_number=new_line, content=line[1:]))
            new_line += 1

    if current is not None:
        files.append(current)

    return files


def changed_file_paths(file_diffs: list[FileDiff]) -> list[str]:
    return [f.file_path for f in file_diffs]
