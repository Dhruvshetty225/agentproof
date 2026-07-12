from pathlib import Path

from agentproof.diff_parser import _parse_unified_diff, parse_diff

DEMO_APP = str(Path(__file__).resolve().parent.parent / "demo-app")

BINARY_MODIFIED_DIFF = """\
diff --git a/logo.png b/logo.png
index 6735744..1e8841a 100644
Binary files a/logo.png and b/logo.png differ
"""

BINARY_ADDED_DIFF = """\
diff --git a/logo.png b/logo.png
new file mode 100644
index 0000000..9727c86
Binary files /dev/null and b/logo.png differ
"""

PURE_RENAME_DIFF = """\
diff --git a/backend/utils.py b/backend/utils_renamed.py
similarity index 100%
rename from backend/utils.py
rename to backend/utils_renamed.py
"""

RENAME_WITH_CONTENT_CHANGE_DIFF = """\
diff --git a/backend/auth.py b/backend/auth_handler.py
similarity index 95%
rename from backend/auth.py
rename to backend/auth_handler.py
index 06944d8..1a299e5 100644
--- a/backend/auth.py
+++ b/backend/auth_handler.py
@@ -57,3 +56,0 @@ def validate_reset_token(raw_token: str) -> str:
-    if is_expired(token):
-        raise ValueError("reset token has expired")
-
"""


def test_parse_diff_returns_both_changed_files():
    file_diffs = parse_diff(DEMO_APP, "main", "ai-fix")
    paths = {f.file_path for f in file_diffs}
    assert paths == {"backend/auth.py", "backend/utils.py"}


def test_parse_diff_detects_deleted_lines_in_auth():
    file_diffs = parse_diff(DEMO_APP, "main", "ai-fix")
    auth_diff = next(f for f in file_diffs if f.file_path == "backend/auth.py")

    assert len(auth_diff.deleted_lines) == 3
    deleted_content = " ".join(line.content for line in auth_diff.deleted_lines)
    assert "is_expired" in deleted_content
    assert "expired" in deleted_content
    assert all(line.line_number > 0 for line in auth_diff.deleted_lines)


def test_parse_diff_detects_added_lines_in_utils():
    file_diffs = parse_diff(DEMO_APP, "main", "ai-fix")
    utils_diff = next(f for f in file_diffs if f.file_path == "backend/utils.py")

    assert len(utils_diff.added_lines) >= 1
    added_content = " ".join(line.content for line in utils_diff.added_lines)
    assert "sk-1234secret" in added_content
    assert all(line.line_number > 0 for line in utils_diff.added_lines)


def test_is_test_file_detection():
    file_diffs = parse_diff(DEMO_APP, "main", "ai-fix")
    for file_diff in file_diffs:
        assert file_diff.is_test_file is False


def test_binary_modified_file_is_captured_and_flagged_binary():
    file_diffs = _parse_unified_diff(BINARY_MODIFIED_DIFF)
    assert len(file_diffs) == 1
    assert file_diffs[0].file_path == "logo.png"
    assert file_diffs[0].is_binary is True
    assert file_diffs[0].added_lines == []
    assert file_diffs[0].deleted_lines == []


def test_binary_added_file_resolves_path_from_b_side():
    file_diffs = _parse_unified_diff(BINARY_ADDED_DIFF)
    assert len(file_diffs) == 1
    assert file_diffs[0].file_path == "logo.png"
    assert file_diffs[0].is_binary is True


def test_pure_rename_is_captured_with_no_content_change():
    file_diffs = _parse_unified_diff(PURE_RENAME_DIFF)
    assert len(file_diffs) == 1
    file_diff = file_diffs[0]
    assert file_diff.file_path == "backend/utils_renamed.py"
    assert file_diff.old_path == "backend/utils.py"
    assert file_diff.is_rename is True
    assert file_diff.is_pure_rename is True
    assert file_diff.added_lines == []
    assert file_diff.deleted_lines == []


def test_rename_with_content_change_still_parses_deleted_lines():
    file_diffs = _parse_unified_diff(RENAME_WITH_CONTENT_CHANGE_DIFF)
    assert len(file_diffs) == 1
    file_diff = file_diffs[0]
    assert file_diff.file_path == "backend/auth_handler.py"
    assert file_diff.old_path == "backend/auth.py"
    assert file_diff.is_rename is True
    assert file_diff.is_pure_rename is False
    assert len(file_diff.deleted_lines) == 3
    assert "is_expired" in file_diff.deleted_lines[0].content
