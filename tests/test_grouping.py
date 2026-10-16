"""Grouping findings that come from one deleted block."""

from agentproof.diff_parser import ChangedLine, FileDiff
from agentproof.engine import calculate_risk_score, collect_findings
from agentproof.grouping import block_groups, group_deleted_blocks
from agentproof.schema import DiffSide, Finding, Severity


def _deleted_file(path: str, start: int, lines: list) -> FileDiff:
    return FileDiff(
        file_path=path,
        deleted_lines=[ChangedLine(start + i, content) for i, content in enumerate(lines)],
    )


def _finding(rule_id, path, line, severity=Severity.HIGH, side=DiffSide.OLD) -> Finding:
    return Finding(rule_id, severity, "t", path, line, f"line {line}", "r", side=side)


# --- block_groups: which flagged lines belong together ----------------------------


def test_if_statement_and_its_body_form_one_group():
    lines = _deleted_file("a.py", 57, [
        "    if is_expired(token):",
        '        raise ValueError("reset token has expired")',
        "",
    ]).deleted_lines
    assert block_groups(lines, {57, 58}) == [[57, 58]]


def test_adjacent_independent_checks_stay_separate():
    lines = _deleted_file("a.py", 10, [
        "    if not user.is_authorized():",
        "        raise Forbidden()",
        "    if not verify_token(t):",
        "        raise Forbidden()",
    ]).deleted_lines
    assert block_groups(lines, {10, 12}) == [[10], [12]]


def test_adjacent_decorators_stay_separate():
    lines = _deleted_file("a.py", 4, ["@login_required", "@require_role('admin')", "def view():"]).deleted_lines
    assert block_groups(lines, {4, 5}) == [[4], [5]]


def test_multi_line_condition_is_one_group():
    lines = _deleted_file("a.py", 20, [
        "    if (user.is_authorized()",
        "            and check_permission(user, 'edit')):",
        "        return True",
    ]).deleted_lines
    assert block_groups(lines, {20, 21}) == [[20, 21]]


def test_nested_check_inside_a_removed_block_joins_that_block():
    lines = _deleted_file("a.py", 30, [
        "    if not user.is_authorized():",
        "        audit_log('denied')",
        "        check_permission(user, 'x')",
    ]).deleted_lines
    assert block_groups(lines, {30, 32}) == [[30, 32]]


def test_checks_inside_a_deleted_function_stay_separate():
    # The unflagged "def" line does not open a group, so the two checks at
    # the same indentation remain two separate findings.
    lines = _deleted_file("a.py", 40, [
        "def view(request):",
        "    if not request.user.is_authenticated:",
        "        return redirect('/')",
        "    verify_token(request.token)",
    ]).deleted_lines
    assert block_groups(lines, {41, 43}) == [[41], [43]]


def test_gap_of_unchanged_lines_ends_a_group():
    file_diff = FileDiff(
        file_path="a.py",
        deleted_lines=[
            ChangedLine(10, "    if is_expired(token):"),
            ChangedLine(15, '        raise ValueError("token expired")'),
        ],
    )
    assert block_groups(file_diff.deleted_lines, {10, 15}) == [[10], [15]]


def test_blank_line_inside_a_block_does_not_end_it():
    lines = _deleted_file("a.py", 1, [
        "    if not has_access(user):",
        "",
        "        raise PermissionError('denied')",
    ]).deleted_lines
    assert block_groups(lines, {1, 3}) == [[1, 3]]


# --- group_deleted_blocks: merging findings ------------------------------------


def test_same_block_findings_merge_into_one_with_a_line_range():
    file_diff = _deleted_file("backend/auth.py", 57, [
        "    if is_expired(token):",
        '        raise ValueError("reset token has expired")',
    ])
    findings = [
        _finding("AUTH001", "backend/auth.py", 57),
        _finding("AUTH001", "backend/auth.py", 58),
    ]
    merged = group_deleted_blocks(findings, [file_diff])
    assert len(merged) == 1
    assert merged[0].line_number == 57
    assert merged[0].end_line_number == 58
    assert merged[0].location == "backend/auth.py:57-58 (deleted, base line numbers)"
    assert merged[0].evidence == "line 57\nline 58"


def test_merged_finding_keeps_the_worst_severity():
    file_diff = _deleted_file("a.py", 1, ["    if is_expired(token):", "        deny()"])
    findings = [
        _finding("AUTH001", "a.py", 1, Severity.MEDIUM),
        _finding("AUTH001", "a.py", 2, Severity.CRITICAL),
    ]
    assert group_deleted_blocks(findings, [file_diff])[0].severity == Severity.CRITICAL


def test_same_line_numbers_in_different_files_are_not_merged():
    lines = ["    if is_expired(token):", "        deny()"]
    file_diffs = [_deleted_file("a.py", 1, lines), _deleted_file("b.py", 1, lines)]
    findings = [_finding("AUTH001", "a.py", 1), _finding("AUTH001", "b.py", 2)]
    assert group_deleted_blocks(findings, file_diffs) == findings


def test_different_rules_on_one_block_are_not_merged():
    file_diff = _deleted_file("a.py", 1, ["    if is_expired(token):", "        deny()"])
    findings = [_finding("AUTH001", "a.py", 1), _finding("OTHER001", "a.py", 2)]
    assert group_deleted_blocks(findings, [file_diff]) == findings


def test_added_line_and_file_level_findings_are_never_grouped():
    file_diff = FileDiff(
        file_path="a.py",
        added_lines=[ChangedLine(1, "    if x:"), ChangedLine(2, "        y()")],
    )
    findings = [
        _finding("LOG001", "a.py", 1, side=DiffSide.NEW),
        _finding("LOG001", "a.py", 2, side=DiffSide.NEW),
        Finding("TESTCOV001", Severity.MEDIUM, "t", "a.py", None, "e", "r"),
    ]
    assert group_deleted_blocks(findings, [file_diff]) == findings


def test_original_order_is_kept():
    file_diff = _deleted_file("a.py", 1, ["    if is_expired(token):", "        deny()"])
    first = Finding("SECRET001", Severity.CRITICAL, "t", "b.py", 9, "e", "r", side=DiffSide.NEW)
    findings = [first, _finding("AUTH001", "a.py", 1), _finding("AUTH001", "a.py", 2)]
    grouped = group_deleted_blocks(findings, [file_diff])
    assert [f.rule_id for f in grouped] == ["SECRET001", "AUTH001"]


# --- end to end through the engine -------------------------------------------------


def test_deleted_if_block_is_scored_once():
    file_diff = _deleted_file("backend/auth.py", 57, [
        "    if is_expired(token):",
        '        raise ValueError("reset token has expired")',
        "",
    ])
    findings, _ignored = collect_findings([file_diff])
    auth_findings = [f for f in findings if f.rule_id == "AUTH001"]
    assert len(auth_findings) == 1
    assert auth_findings[0].location == "backend/auth.py:57-58 (deleted, base line numbers)"
    assert calculate_risk_score(auth_findings) == 20


def test_two_independent_deleted_checks_are_scored_twice():
    file_diff = _deleted_file("app/views.py", 10, [
        "    if not user.is_authorized():",
        "        raise Forbidden()",
        "    if not verify_token(t):",
        "        raise Forbidden()",
    ])
    findings, _ignored = collect_findings([file_diff])
    auth_findings = [f for f in findings if f.rule_id == "AUTH001"]
    assert [f.line_number for f in auth_findings] == [10, 12]
    assert calculate_risk_score(auth_findings) == 40
