"""Build small throwaway git repositories for tests.

Identity and signing are passed with ``git -c`` for each command, so the
developer's global git configuration is neither used nor changed.
"""

import subprocess
from pathlib import Path

_GIT_SETTINGS = [
    "-c", "user.name=AgentProof Test",
    "-c", "user.email=test@example.com",
    "-c", "commit.gpgsign=false",
]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *_GIT_SETTINGS, *args], check=True, capture_output=True)


def _write(repo: Path, files: dict) -> None:
    for relative_path, content in files.items():
        path = repo / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def make_repo(path: Path, base_files: dict, branch_files: dict, later_base_files=None) -> str:
    """Create `main` with `base_files`, then branch `feature` that writes `branch_files`.

    If `later_base_files` is given, `main` gets one more commit with those
    files *after* `feature` was created, as when main moves on during review.
    """
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _write(path, base_files)
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "--allow-empty", "-m", "base")
    _git(path, "checkout", "-q", "-b", "feature")
    _write(path, branch_files)
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "--allow-empty", "-m", "change")
    if later_base_files:
        _git(path, "checkout", "-q", "main")
        _write(path, later_base_files)
        _git(path, "add", "-A")
        _git(path, "commit", "-q", "-m", "later base change")
        _git(path, "checkout", "-q", "feature")
    return str(path)
