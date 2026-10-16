"""TESTCOV001 and FileDiff.is_test_file: recognizing changed test files."""

import pytest

from agentproof.diff_parser import ChangedLine, FileDiff
from agentproof.rules import test_coverage


def _changed(path: str) -> FileDiff:
    return FileDiff(file_path=path, added_lines=[ChangedLine(1, "x = 1")])


@pytest.mark.parametrize(
    "path",
    [
        # test/ and tests/ directory components, at any depth.
        "tests/helpers.py",
        "test/helpers.py",
        "src/test/java/com/app/Util.java",
        "pkg/tests/fixtures.go",
        "Tests/helpers.py",
        # Python conventions.
        "tests/test_auth.py",
        "test_auth.py",
        "app/auth_test.py",
        "conftest.py",
        "src/conftest.py",
        # JavaScript / TypeScript conventions.
        "web/app.test.js",
        "web/app.test.ts",
        "web/app.spec.js",
        "web/app.spec.ts",
        # Java and Go conventions.
        "src/main/java/com/app/FooTest.java",
        "pkg/server_test.go",
    ],
)
def test_recognizes_test_file_conventions(path):
    assert FileDiff(file_path=path).is_test_file is True


@pytest.mark.parametrize(
    "path",
    [
        "src/latest.py",
        "src/contest.py",
        "attestation/verify.py",
        "src/testing_utils.py",
        "src/contest_test_data.py",
        "src/conftest_helpers.py",
        "web/testimonial.ts",
        "web/spec.js",
        "web/app.js",
        "src/main/java/com/app/Latest.java",
        "src/main/java/com/app/Contest.java",
        "pkg/contest.go",
        "pkg/attest.go",
        "latest/app.py",
    ],
)
def test_similar_production_paths_are_not_tests(path):
    assert FileDiff(file_path=path).is_test_file is False


@pytest.mark.parametrize(
    "production, test",
    [
        ("lib/util.py", "tests/helpers.py"),
        ("app/models.py", "conftest.py"),
        ("web/app.js", "web/app.test.js"),
        ("web/app.ts", "web/app.spec.ts"),
        ("pkg/server.go", "pkg/server_test.go"),
        ("src/main/java/Foo.java", "src/main/java/FooTest.java"),
    ],
)
def test_production_change_with_recognized_test_update_is_not_flagged(production, test):
    assert test_coverage.check([_changed(production), _changed(test)]) == []


@pytest.mark.parametrize(
    "production",
    ["lib/util.py", "web/app.js", "web/app.ts", "pkg/server.go", "src/main/java/Foo.java"],
)
def test_production_change_without_tests_is_flagged(production):
    findings = test_coverage.check([_changed(production)])
    assert len(findings) == 1
    assert production in findings[0].evidence


def test_look_alike_production_file_does_not_count_as_a_test_update():
    findings = test_coverage.check([_changed("src/app.py"), _changed("src/latest.py")])
    assert len(findings) == 1
    assert "src/app.py" in findings[0].evidence
    assert "src/latest.py" in findings[0].evidence
