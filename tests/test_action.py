"""The shell steps of action.yml, run locally with a stand-in `agentproof`.

These run the exact `run:` scripts from action.yml with bash. A fake
`agentproof` on PATH returns chosen exit codes, so the tests check how the
Action turns AgentProof's results into its `exit-code` output and the step's
own exit status. They do not run the Action on GitHub.
"""

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

ACTION = Path(__file__).resolve().parent.parent / "action.yml"


def _run_script(step_marker: str) -> str:
    """The `run: |` block of the step that contains `step_marker`."""
    text = ACTION.read_text(encoding="utf-8")
    step = text[text.index(step_marker):]
    match = re.search(r"\n      run: \|\n((?:        .*\n|\n)+)", step)
    return "\n".join(line[8:] for line in match.group(1).splitlines())


def _fake_agentproof(bin_dir: Path, codes: list) -> None:
    """An `agentproof` that exits with codes[0] on the first call, codes[1] on the second."""
    counter = bin_dir / "calls"
    script = bin_dir / "agentproof"
    script.write_text(
        "#!/bin/bash\n"
        f'n=$(cat "{counter}" 2>/dev/null || echo 0)\n'
        f'echo $((n + 1)) > "{counter}"\n'
        f"codes=({' '.join(str(code) for code in codes)})\n"
        'exit "${codes[$n]}"\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


def _run_audit_step(tmp_path: Path, codes: list) -> tuple:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_agentproof(bin_dir, codes)
    output = tmp_path / "github_output"
    output.write_text("")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_WORKSPACE": str(tmp_path),
        "GITHUB_OUTPUT": str(output),
        "AP_BASE": "base-sha",
        "AP_HEAD": "head-sha",
        "AP_TASK": "",
        "AP_FORMAT": "sarif",
        "AP_OUTPUT": "agentproof.sarif",
        "AP_CONFIG": "",
    }
    result = subprocess.run(["bash", "-c", _run_script("id: audit")], env=env,
                            capture_output=True, text=True)
    return result, output.read_text()


@pytest.mark.parametrize(("codes", "expected"), [
    ([0, 0], "exit-code=0"),   # approve or review
    ([1, 1], "exit-code=1"),   # REJECT: the report file is still written
    ([1, 2], "exit-code=2"),   # REJECT, but the report could not be written
    ([0, 2], "exit-code=2"),   # approve, but the report could not be written
    ([2, 2], "exit-code=2"),   # the audit itself failed
])
def test_audit_step_reports_the_right_exit_code(tmp_path, codes, expected):
    result, output = _run_audit_step(tmp_path, codes)
    assert result.returncode == 0  # the step records the code; "Apply result" acts on it
    assert output.strip() == expected


def test_a_report_writing_error_is_surfaced(tmp_path):
    result, _ = _run_audit_step(tmp_path, [1, 2])
    assert "::error::AgentProof could not write the report file" in result.stdout


def test_a_reject_alone_is_not_reported_as_a_writing_error(tmp_path):
    result, _ = _run_audit_step(tmp_path, [1, 1])
    assert "::error::" not in result.stdout


@pytest.mark.parametrize(("exit_code", "fail_on_reject", "expected"), [
    ("0", "true", 0),
    ("1", "true", 1),
    ("1", "false", 0),
    ("2", "true", 2),
    ("2", "false", 2),
])
def test_apply_step_fails_only_when_it_should(exit_code, fail_on_reject, expected):
    env = {**os.environ, "EXIT_CODE": exit_code, "FAIL_ON_REJECT": fail_on_reject}
    result = subprocess.run(["bash", "-c", _run_script("name: Apply result")], env=env,
                            capture_output=True, text=True)
    assert result.returncode == expected
