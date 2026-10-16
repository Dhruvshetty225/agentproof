"""The agentproof command line: formats, output files, exit codes and errors."""

import io
import json

import pytest
from rich.console import Console
from typer.testing import CliRunner

from agentproof import __version__, cli
from tests.git_helpers import make_repo

FAKE_KEY = "sk-" + "abcd1234efgh"  # fabricated; built by concatenation

# Deletes an expiry check (AUTH001, high) and adds a key (SECRET001, critical)
# with no test change (TESTCOV001, medium): 20 + 30 + 10 = 60 -> REJECT.
RISKY_BASE = {
    "app/auth.py": (
        "def check(token):\n"
        "    if is_expired(token):\n"
        "        raise ValueError('expired')\n"
        "    return True\n"
    ),
}
RISKY_BRANCH = {
    "app/auth.py": "def check(token):\n    return True\n",
    "app/config.py": f'api_key = "{FAKE_KEY}"\n',
}

# A credential-named literal (SECRET001, high) without tests: 20 + 10 = 30 -> REVIEW.
REVIEW_BRANCH = {"app/config.py": 'db_password = "fake-password"\n'}

# A code change with a matching test change: no findings -> APPROVE.
SAFE_BASE = {"app/util.py": "x = 1\n"}
SAFE_BRANCH = {"app/util.py": "x = 2\n", "tests/test_util.py": "def test_x():\n    assert True\n"}


@pytest.fixture
def risky_repo(tmp_path):
    return make_repo(tmp_path / "risky", RISKY_BASE, RISKY_BRANCH)


@pytest.fixture
def safe_repo(tmp_path):
    return make_repo(tmp_path / "safe", SAFE_BASE, SAFE_BRANCH)


def _audit(repo, *extra):
    return CliRunner().invoke(cli.app, ["audit", "--repo", repo, "--branch", "feature", *extra])


# --- exit codes ---------------------------------------------------------------------


def test_reject_exits_with_1(risky_repo):
    result = _audit(risky_repo)
    assert result.exit_code == 1
    assert "REJECT" in result.stdout


def test_review_exits_with_0(tmp_path):
    repo = make_repo(tmp_path / "review", {"app/config.py": ""}, REVIEW_BRANCH)
    result = _audit(repo)
    assert result.exit_code == 0
    assert "REVIEW" in result.stdout


def test_approve_exits_with_0(safe_repo):
    result = _audit(safe_repo)
    assert result.exit_code == 0
    assert "APPROVE" in result.stdout


# --- terminal format (default) ------------------------------------------------------


def test_default_format_is_terminal_on_stdout_with_nothing_on_stderr(risky_repo):
    result = _audit(risky_repo)
    assert "AgentProof Audit" in result.stdout
    assert result.stderr == ""


def test_empty_findings_message_does_not_claim_safety(safe_repo):
    result = _audit(safe_repo)
    assert "No findings from AgentProof's rules." in result.stdout
    assert "does not prove the change is safe" in result.stdout
    assert "safe to merge" not in result.stdout


def test_terminal_report_can_be_written_to_a_file(risky_repo, tmp_path):
    target = tmp_path / "report.txt"
    result = _audit(risky_repo, "--output", str(target))
    text = target.read_text(encoding="utf-8")
    assert "AgentProof Audit" in text
    assert "\x1b[" not in text  # no terminal color codes in the file
    assert result.stdout == ""
    assert "terminal report written to" in result.stderr


def test_deleted_lines_are_labelled_with_base_line_numbers(risky_repo, monkeypatch):
    output = io.StringIO()
    monkeypatch.setattr(cli, "console", Console(file=output, width=400, no_color=True))
    _audit(risky_repo)
    assert "app/auth.py:2-3 (deleted, base line numbers)" in output.getvalue()


# --- machine-readable formats --------------------------------------------------------


def test_json_on_stdout_is_pure_json(risky_repo):
    result = _audit(risky_repo, "--format", "json")
    data = json.loads(result.stdout)  # fails if anything else was printed
    assert data["recommendation"] == "reject"
    assert result.stderr == ""
    assert result.exit_code == 1


def test_json_with_output_file_keeps_stdout_empty(risky_repo, tmp_path):
    target = tmp_path / "out.json"
    result = _audit(risky_repo, "--format", "json", "--output", str(target))
    assert result.stdout == ""
    assert json.loads(target.read_text(encoding="utf-8"))["risk_score"] == 60
    assert "json report written to" in result.stderr


def test_sarif_on_stdout_is_pure_json(risky_repo):
    result = _audit(risky_repo, "--format", "sarif")
    assert json.loads(result.stdout)["version"] == "2.1.0"
    assert result.stderr == ""


def test_format_name_is_case_insensitive(risky_repo):
    result = _audit(risky_repo, "--format", "SARIF")
    assert json.loads(result.stdout)["version"] == "2.1.0"


@pytest.mark.parametrize(
    "file_name, check",
    [
        ("report.html", lambda text: text.lstrip().startswith("<!DOCTYPE html>")),
        ("report.HTM", lambda text: text.lstrip().startswith("<!DOCTYPE html>")),
        ("report.json", lambda text: json.loads(text)["schema_version"] == 1),
        ("report.sarif", lambda text: json.loads(text)["version"] == "2.1.0"),
        ("report.txt", lambda text: "AgentProof Audit" in text),
    ],
)
def test_format_is_inferred_from_the_output_extension(risky_repo, tmp_path, file_name, check):
    target = tmp_path / file_name
    _audit(risky_repo, "--output", str(target))
    assert check(target.read_text(encoding="utf-8"))


def test_explicit_format_wins_over_the_extension(risky_repo, tmp_path):
    target = tmp_path / "report.html"
    _audit(risky_repo, "--format", "json", "--output", str(target))
    assert json.loads(target.read_text(encoding="utf-8"))["schema_version"] == 1


@pytest.mark.parametrize("report_format", ["terminal", "json", "sarif", "html"])
def test_no_format_shows_the_full_secret(risky_repo, monkeypatch, report_format):
    output = io.StringIO()
    monkeypatch.setattr(cli, "console", Console(file=output, width=400, no_color=True))
    result = _audit(risky_repo, "--format", report_format)
    text = output.getvalue() + result.stdout
    assert FAKE_KEY not in text
    assert "sk-a****" in text  # the evidence was rendered, in masked form


# --- usage and runtime errors -----------------------------------------------------------


def test_unknown_format_is_a_usage_error(risky_repo):
    assert _audit(risky_repo, "--format", "xml").exit_code == 2


def test_missing_required_option_is_a_usage_error(risky_repo):
    result = CliRunner().invoke(cli.app, ["audit", "--repo", risky_repo])
    assert result.exit_code == 2


def test_nonexistent_repository_is_reported_as_a_git_error(tmp_path):
    result = _audit(str(tmp_path / "missing"))
    assert result.exit_code == 2
    assert "Git error" in result.stderr
    assert result.stdout == ""


def test_unknown_branch_is_reported_as_a_git_error(risky_repo):
    result = CliRunner().invoke(
        cli.app, ["audit", "--repo", risky_repo, "--branch", "no-such-branch"]
    )
    assert result.exit_code == 2
    assert "Git error" in result.stderr


def test_unknown_base_is_reported_as_a_git_error(risky_repo):
    result = _audit(risky_repo, "--base", "no-such-base")
    assert result.exit_code == 2
    assert "Git error" in result.stderr


def test_unwritable_output_path_is_reported(risky_repo, tmp_path):
    result = _audit(risky_repo, "--output", str(tmp_path / "no-such-dir" / "r.json"))
    assert result.exit_code == 2
    assert "Cannot write report" in result.stderr


def test_version_command():
    result = CliRunner().invoke(cli.app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"agentproof {__version__}"
