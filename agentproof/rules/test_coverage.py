"""Flag production code changes that ship without any corresponding test update.

This is test-file-change detection, not test coverage: a file counts as a
test when its path matches a naming convention (see FileDiff.is_test_file).
Known limitation: any changed test file suppresses the warning for the whole
diff, even a test that is unrelated to the production change or a test file
that was deleted.
"""

from __future__ import annotations

from agentproof.diff_parser import FileDiff
from agentproof.schema import Finding, Severity

RULE_ID = "TESTCOV001"

_SOURCE_CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rb",
    ".java",
    ".kt",
    ".kts",
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".hpp",
    ".cs",
    ".php",
    ".rs",
    ".swift",
    ".scala",
    ".sh",
    ".bash",
}


def _is_source_file(file_diff: FileDiff) -> bool:
    path = file_diff.file_path.lower()
    return any(path.endswith(ext) for ext in _SOURCE_CODE_EXTENSIONS)


def check(file_diffs: list[FileDiff], task: str | None = None) -> list[Finding]:
    production_files = [f for f in file_diffs if not f.is_test_file and _is_source_file(f)]
    test_files = [f for f in file_diffs if f.is_test_file]

    if not production_files or test_files:
        return []

    file_list = ", ".join(f.file_path for f in production_files)
    return [
        Finding(
            rule_id=RULE_ID,
            severity=Severity.MEDIUM,
            title="Production code changed without a corresponding test update",
            file_path=file_list,
            line_number=None,
            evidence=f"Changed production files with no test changes: {file_list}",
            recommendation=(
                "Add or update tests that cover this change before merging, "
                "especially for behavior changes made by an AI agent."
            ),
        )
    ]
