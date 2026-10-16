"""parse_diff compares the branch with its merge base (git diff base...branch)."""

from agentproof.diff_parser import parse_diff
from agentproof.engine import run_audit
from tests.git_helpers import make_repo


def _repo_where_main_moved_on(tmp_path):
    # After `feature` branches off, main adds a new permission check. A plain
    # two-dot diff (main..feature) would show that check as *deleted* by the
    # feature branch, which never touched it.
    return make_repo(
        tmp_path / "repo",
        base_files={"app/views.py": "def view(user):\n    return render(user)\n"},
        branch_files={"app/readme.txt": "docs only\n"},
        later_base_files={
            "app/views.py": (
                "def view(user):\n"
                "    check_permission(user, 'view')\n"
                "    return render(user)\n"
            )
        },
    )


def test_changes_made_on_base_after_branching_are_not_attributed_to_the_branch(tmp_path):
    repo = _repo_where_main_moved_on(tmp_path)
    file_diffs = parse_diff(repo, "main", "feature")
    assert [f.file_path for f in file_diffs] == ["app/readme.txt"]


def test_no_false_auth_finding_when_base_moved_on(tmp_path):
    repo = _repo_where_main_moved_on(tmp_path)
    report = run_audit(repo, "main", "feature")
    assert "AUTH001" not in {f.rule_id for f in report.findings}


def test_changes_made_on_the_branch_are_still_found(tmp_path):
    repo = make_repo(
        tmp_path / "repo",
        base_files={"app/views.py": "def view(user):\n    check_permission(user, 'view')\n"},
        branch_files={"app/views.py": "def view(user):\n    pass\n"},
        later_base_files={"app/other.py": "x = 1\n"},
    )
    report = run_audit(repo, "main", "feature")
    assert "AUTH001" in {f.rule_id for f in report.findings}
