"""Flag changes AgentProof cannot inspect as text: binary files and pure renames.

Every other rule scans added/deleted line content, which git never provides
for binary files or for renames with no accompanying content change. Without
this rule those changes are invisible to the audit entirely.
"""

from __future__ import annotations

from agentproof.diff_parser import FileDiff
from agentproof.schema import Finding, Severity

RULE_ID = "UNREVIEWABLE001"


def check(file_diffs: list[FileDiff], task: str | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for file_diff in file_diffs:
        if file_diff.is_binary:
            findings.append(
                Finding(
                    rule_id=RULE_ID,
                    severity=Severity.MEDIUM,
                    title="Binary file changed",
                    file_path=file_diff.file_path,
                    line_number=None,
                    evidence=f"'{file_diff.file_path}' is a binary file; its contents cannot be diffed as text.",
                    recommendation=(
                        "Manually inspect this binary file before merging. AgentProof "
                        "cannot scan binary content for risky changes."
                    ),
                )
            )
        elif file_diff.is_pure_rename:
            findings.append(
                Finding(
                    rule_id=RULE_ID,
                    severity=Severity.LOW,
                    title="File renamed with no content change",
                    file_path=file_diff.file_path,
                    line_number=None,
                    evidence=f"'{file_diff.old_path}' was renamed to '{file_diff.file_path}' with no content change.",
                    recommendation=(
                        "Confirm the rename is intentional. Renaming a file is a "
                        "way to move security-relevant code out of reviewers' "
                        "expected paths without changing its content."
                    ),
                )
            )
    return findings
