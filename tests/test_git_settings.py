"""The user's git settings and odd ref names cannot change what AgentProof reads.

Each test points git at its own global config file through GIT_CONFIG_GLOBAL,
so the developer's real configuration is neither used nor changed.
"""

import pytest
from git.exc import GitCommandError
from typer.testing import CliRunner

from agentproof.cli import app
from agentproof.diff_parser import parse_diff
from agentproof.engine import run_audit
from tests.git_helpers import make_repo

BASE = (
    "def view(user, t):\n"
    "    if not user.is_admin():\n"
    "        raise Forbidden()\n"
    "    a = 1\n"
    "    b = 2\n"
    "    if not verify_token(t):\n"
    "        raise Forbidden()\n"
    "    return ok()\n"
)
BRANCH = "def view(user, t):\n    a = 1\n    b = 2\n    return ok()\n"


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "repo", {"app/views.py": BASE}, {"app/views.py": BRANCH})


def _use_git_config(monkeypatch, tmp_path, text):
    config = tmp_path / "gitconfig"
    config.write_text(text)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _auth_lines(repo):
    report = run_audit(repo, "main", "feature")
    return [f.line_number for f in report.findings if f.rule_id == "AUTH001"]


def test_both_deleted_checks_are_found_at_their_base_lines(repo):
    assert _auth_lines(repo) == [2, 6]


def test_an_external_diff_tool_setting_is_ignored(repo, monkeypatch, tmp_path):
    # "true" prints nothing; before the fix the audit saw no changes at all.
    _use_git_config(monkeypatch, tmp_path, "[diff]\n\texternal = true\n")
    assert _auth_lines(repo) == [2, 6]


def test_inter_hunk_context_setting_does_not_shift_line_numbers(repo, monkeypatch, tmp_path):
    # Before the fix the second check was reported at line 4 instead of 6.
    _use_git_config(monkeypatch, tmp_path, "[diff]\n\tinterHunkContext = 10\n")
    assert _auth_lines(repo) == [2, 6]


def test_a_ref_starting_with_a_dash_is_not_read_as_a_git_option(repo, tmp_path):
    target = tmp_path / "written-by-git"
    with pytest.raises(GitCommandError):
        parse_diff(repo, f"--output={target}", "feature")
    assert not list(tmp_path.glob("written-by-git*"))


def test_cli_rejects_a_dash_ref_with_exit_code_2(repo, tmp_path):
    config = tmp_path / "empty.toml"
    config.write_text("")
    target = tmp_path / "written-by-git"
    result = CliRunner().invoke(app, [
        "audit", "--repo", repo, f"--base=--output={target}", "--branch", "feature",
        "--config", str(config),
    ])
    assert result.exit_code == 2
    assert not list(tmp_path.glob("written-by-git*"))
