"""Inline "agentproof: ignore[RULE_ID]" directives."""

import pytest

from agentproof.diff_parser import ChangedLine, FileDiff
from agentproof.engine import collect_findings
from agentproof.ignores import ignored_rule_ids


# --- parsing directives --------------------------------------------------------


@pytest.mark.parametrize(
    "content, expected",
    [
        ('x = "v"  # agentproof: ignore[SECRET001]', {"SECRET001"}),
        ("x()  // agentproof: ignore[LOG001]", {"LOG001"}),
        ("x  # agentproof:ignore[AUTH001]", {"AUTH001"}),
        ("x  # agentproof: ignore[AUTH001, LOG001]", {"AUTH001", "LOG001"}),
        ("x  # agentproof: ignore[ AUTH001 ]", {"AUTH001"}),
        ("x  # agentproof: ignore[FOO999]", {"FOO999"}),  # well-formed, matches no rule
    ],
)
def test_well_formed_directives(content, expected):
    assert ignored_rule_ids(content) == expected


@pytest.mark.parametrize(
    "content",
    [
        "x  # agentproof: ignore",
        "x  # agentproof: ignore[]",
        "x  # agentproof: ignore[auth001]",
        "x  # agentproof: ignore[AUTH001,]",
        "x  # agentproof: ignore[AUTH-001]",
        "x  # agentproof: ignore[*]",
        "x  # AgentProof: ignore[AUTH001]",
        "x  # agentproof ignore[AUTH001]",
        "x  # noqa",
    ],
)
def test_malformed_directives_ignore_nothing(content):
    assert ignored_rule_ids(content) == set()


# --- applying directives to findings ---------------------------------------------


def _added(*lines: str) -> FileDiff:
    return FileDiff(
        file_path="app/config.py",
        added_lines=[ChangedLine(i + 1, content) for i, content in enumerate(lines)],
    )


def _deleted(*lines: str) -> FileDiff:
    return FileDiff(
        file_path="app/views.py",
        deleted_lines=[ChangedLine(i + 10, content) for i, content in enumerate(lines)],
    )


def _rule_ids(findings) -> list:
    return sorted(f.rule_id for f in findings)


def test_directive_on_added_line_ignores_that_rule_on_that_line():
    file_diff = _added('db_password = "hunter2"  # agentproof: ignore[SECRET001]')
    findings, ignored = collect_findings([file_diff])
    assert "SECRET001" not in _rule_ids(findings)
    assert _rule_ids(ignored) == ["SECRET001"]
    assert ignored[0].line_number == 1


def test_directive_for_an_unrelated_rule_ignores_nothing():
    file_diff = _added('db_password = "hunter2"  # agentproof: ignore[LOG001]')
    findings, ignored = collect_findings([file_diff])
    assert "SECRET001" in _rule_ids(findings)
    assert ignored == []


def test_malformed_directive_ignores_nothing():
    file_diff = _added('db_password = "hunter2"  # agentproof: ignore[secret001]')
    findings, ignored = collect_findings([file_diff])
    assert "SECRET001" in _rule_ids(findings)
    assert ignored == []


def test_directive_only_covers_its_own_line():
    file_diff = _added(
        "# agentproof: ignore[SECRET001]",
        'db_password = "hunter2"',
    )
    findings, ignored = collect_findings([file_diff])
    assert "SECRET001" in _rule_ids(findings)
    assert ignored == []


def test_one_directive_can_list_several_rules():
    file_diff = _added('print(f"{password}"); api_key = "sk-abcd1234"  # agentproof: ignore[LOG001, SECRET001]')
    findings, ignored = collect_findings([file_diff])
    assert _rule_ids(ignored) == ["LOG001", "SECRET001"]
    assert "LOG001" not in _rule_ids(findings)
    assert "SECRET001" not in _rule_ids(findings)


def test_directive_on_deleted_line_from_the_base_version_applies():
    file_diff = _deleted("    verify_token(t)  # agentproof: ignore[AUTH001]")
    findings, ignored = collect_findings([file_diff])
    assert "AUTH001" not in _rule_ids(findings)
    assert _rule_ids(ignored) == ["AUTH001"]


def test_added_directive_cannot_silence_a_deletion():
    file_diff = FileDiff(
        file_path="app/views.py",
        deleted_lines=[ChangedLine(10, "    verify_token(t)")],
        added_lines=[ChangedLine(10, "    pass  # agentproof: ignore[AUTH001]")],
    )
    findings, ignored = collect_findings([file_diff])
    assert "AUTH001" in _rule_ids(findings)
    assert ignored == []


def test_ignore_is_per_line_inside_a_deleted_block():
    file_diff = _deleted(
        "    if is_expired(token):  # agentproof: ignore[AUTH001]",
        '        raise ValueError("reset token has expired")',
    )
    findings, ignored = collect_findings([file_diff])
    auth = [f for f in findings if f.rule_id == "AUTH001"]
    assert [f.line_number for f in auth] == [11]
    assert [f.line_number for f in ignored] == [10]


def test_file_level_findings_cannot_be_ignored_inline():
    file_diff = _added("x = 1  # agentproof: ignore[TESTCOV001]")
    findings, ignored = collect_findings([file_diff])
    assert "TESTCOV001" in _rule_ids(findings)
    assert ignored == []
