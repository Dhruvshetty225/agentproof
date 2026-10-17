"""eval/u0.py turns context diffs into exactly what ``git diff -U0`` prints.

Three kinds of evidence:
1. hand-written fixtures for each edge case;
2. git itself as ground truth, on seeded random edits and on the 20
   synthetic cases;
3. end to end: AgentProof's normal path (git -U0 inside run_audit) and the
   evaluation path (to_u0 of the committed pr.diff) give the same findings.
"""

import os
import random
import re
import subprocess

import pytest

from agentproof.diff_parser import _parse_unified_diff
from agentproof.engine import collect_findings, run_audit
from eval.make_synthetic import CASES, OUT_DIR, built_repo, make_diff
from eval.u0 import changed_lines, check_u0, to_u0

HEADER = "diff --git a/f.txt b/f.txt\nindex 1111111..2222222 100644\n--- a/f.txt\n+++ b/f.txt\n"


def _hunks_only(diff_text):
    """Drop git's optional function-name text after a hunk header."""
    return re.sub(r"^(@@ [^@]* @@).*$", r"\1", diff_text, flags=re.MULTILINE)


# --- 1. hand-written fixtures ------------------------------------------------------


def test_context_between_changes_splits_the_hunk():
    diff = HEADER + "@@ -1,7 +1,7 @@ def f():\n a\n-b\n+B\n c\n d\n e\n-f\n+F\n g\n"
    assert to_u0(diff) == HEADER + "@@ -2 +2 @@\n-b\n+B\n@@ -6 +6 @@\n-f\n+F\n"


def test_pure_addition_and_pure_deletion_use_gits_line_before_convention():
    diff = HEADER + "@@ -1,6 +1,6 @@\n a\n+x\n+y\n b\n c\n-d\n-e\n f\n"
    assert to_u0(diff) == HEADER + "@@ -1,0 +2,2 @@\n+x\n+y\n@@ -4,2 +5,0 @@\n-d\n-e\n"


def test_new_and_deleted_files_are_unchanged():
    new_file = HEADER + "@@ -0,0 +1,2 @@\n+a\n+b\n"
    deleted_file = HEADER + "@@ -1,2 +0,0 @@\n-a\n-b\n"
    assert to_u0(new_file) == new_file
    assert to_u0(deleted_file) == deleted_file


def test_no_newline_marker_stays_with_a_changed_line_and_goes_with_context():
    after_change = HEADER + "@@ -1,2 +1,2 @@\n a\n-b\n\\ No newline at end of file\n+b\n"
    assert to_u0(after_change) == HEADER + "@@ -2 +2 @@\n-b\n\\ No newline at end of file\n+b\n"
    after_context = HEADER + "@@ -1,3 +1,3 @@\n-a\n+A\n b\n c\n\\ No newline at end of file\n"
    assert to_u0(after_context) == HEADER + "@@ -1 +1 @@\n-a\n+A\n"


def test_lines_starting_with_dashes_or_pluses_are_content():
    diff = HEADER + "@@ -1,3 +1,3 @@\n SELECT 1;\n--- old comment\n+++ new comment\n SELECT 2;\n"
    converted = to_u0(diff)
    assert converted == HEADER + "@@ -2 +2 @@\n--- old comment\n+++ new comment\n"
    (file_diff,) = _parse_unified_diff(converted)
    assert [(l.line_number, l.content) for l in file_diff.deleted_lines] == [(2, "-- old comment")]
    assert [(l.line_number, l.content) for l in file_diff.added_lines] == [(2, "++ new comment")]


def test_binary_and_rename_sections_pass_through():
    diff = (
        "diff --git a/logo.png b/logo.png\nindex 1..2 100644\nBinary files a/logo.png and b/logo.png differ\n"
        "diff --git a/old.py b/new.py\nsimilarity index 100%\nrename from old.py\nrename to new.py\n"
    )
    assert to_u0(diff) == diff


def test_crlf_content_is_preserved():
    diff = HEADER + "@@ -1,2 +1,2 @@\n a\r\n-b\r\n+B\r\n"
    assert to_u0(diff) == HEADER + "@@ -2 +2 @@\n-b\r\n+B\r\n"


def test_a_hunk_shorter_than_its_header_is_rejected():
    with pytest.raises(ValueError):
        to_u0(HEADER + "@@ -1,3 +1,3 @@\n a\n-b\n+B\n")


def test_check_u0_rejects_wrong_counts_and_leftover_context():
    with pytest.raises(ValueError):
        check_u0(HEADER + "@@ -2,2 +2 @@\n-b\n+B\n")
    with pytest.raises(ValueError):
        check_u0(HEADER + "@@ -2 +2 @@\n-b\n+B\n c\n")
    with pytest.raises(ValueError):
        check_u0(HEADER + "@@ -6 +6 @@\n-f\n+F\n@@ -2 +2 @@\n-b\n+B\n")
    check_u0(HEADER + "@@ -2 +2 @@\n-b\n+B\n@@ -6 +6 @@\n-f\n+F\n")


def test_changed_lines_ignore_file_headers():
    diff = HEADER + "@@ -1,2 +1,2 @@\n a\n-b\n+B\n"
    assert changed_lines(diff) == ["-b", "+B"]


# --- 2. git as ground truth ------------------------------------------------------------

# Run git without the user's own configuration, so settings such as
# diff.algorithm cannot change its output.
_GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
_VOCABULARY = ["a", "b", "c", "def f():", "    return 1", "", "-- sql comment", "---",
               "++i;", "+++", "  indented", "x = 1", "x = 2", "}"]


def _random_text(rng):
    lines = [rng.choice(_VOCABULARY) for _ in range(rng.randint(0, 12))]
    text = "\n".join(lines)
    if lines and rng.random() < 0.8:
        text += "\n"  # most files end with a newline; some do not
    return text


def _mutate(rng, text):
    lines = text.split("\n")
    for _ in range(rng.randint(1, 4)):
        position = rng.randint(0, len(lines))
        action = rng.choice(["insert", "delete", "replace"])
        if action == "insert":
            lines.insert(position, rng.choice(_VOCABULARY))
        elif lines and position < len(lines):
            if action == "delete":
                del lines[position]
            else:
                lines[position] = rng.choice(_VOCABULARY)
    return "\n".join(lines)


def _git_diff(old_path, new_path, *options):
    result = subprocess.run(
        ["git", "diff", "--no-index", "--no-color", *options, str(old_path), str(new_path)],
        capture_output=True, env=_GIT_ENV,
    )
    assert result.returncode in (0, 1), result.stderr
    return result.stdout.decode("utf-8")


def test_matches_git_on_seeded_random_edits(tmp_path):
    rng = random.Random(20261016)
    compared = 0
    for case in range(200):
        old_text = _random_text(rng)
        new_text = _mutate(rng, old_text)
        old_path, new_path = tmp_path / f"old{case}.txt", tmp_path / f"new{case}.txt"
        old_path.write_bytes(old_text.encode("utf-8"))
        new_path.write_bytes(new_text.encode("utf-8"))
        with_context = _git_diff(old_path, new_path)
        if not with_context:
            continue  # the mutation happened to change nothing
        converted = to_u0(with_context)
        assert _hunks_only(converted) == _hunks_only(_git_diff(old_path, new_path, "-U0")), case
        assert changed_lines(converted) == changed_lines(with_context)
        check_u0(converted)
        compared += 1
    assert compared >= 150  # most random edits must produce a real diff


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_matches_git_on_synthetic_cases(case):
    committed = (OUT_DIR / case["id"] / "pr.diff").read_text(encoding="utf-8")
    assert _hunks_only(to_u0(committed)) == _hunks_only(make_diff(case, "-U0"))


# --- 3. end to end -------------------------------------------------------------------


def _keys(findings):
    return sorted((f.rule_id, f.file_path, f.line_number, f.end_line_number, str(f.side)) for f in findings)


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_evaluation_path_gives_the_same_findings_as_agentproof(case):
    task = f"{case['title']}\n\n{case['description']}"
    with built_repo(case) as repo:
        report = run_audit(str(repo), "main", "feature", task=task)
    committed = (OUT_DIR / case["id"] / "pr.diff").read_text(encoding="utf-8")
    findings, ignored = collect_findings(_parse_unified_diff(to_u0(committed)), task=task)
    assert _keys(findings) == _keys(report.findings)
    assert _keys(ignored) == _keys(report.ignored_findings)
