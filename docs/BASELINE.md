# Baseline Before the Upgrade

This file records the state of AgentProof before the upgrade work began, so
later results can be compared against the same starting point.

## Original commit

| Item | Value |
|------|-------|
| Repository | https://github.com/Dhruvshetty225/agentproof |
| Branch | `main` |
| Commit | `819cbb200640f5753c4c4ca8d5f0bb770ec71889` |
| Recorded on | 2026-10-16 |

To check out the original version next to the working copy without
switching the active checkout:

```bash
git worktree add ../agentproof-baseline 819cbb200640f5753c4c4ca8d5f0bb770ec71889
```

## Environment used for the baseline run

| Item | Value |
|------|-------|
| OS | macOS 26.2 (arm64) |
| Python | 3.12.6 |
| Git | 2.50.1 |

Installed package versions (`pip freeze`, excluding AgentProof itself):

```
annotated-doc==0.0.5
gitdb==4.0.12
GitPython==3.2.1
iniconfig==2.3.1
Jinja2==3.1.6
markdown-it-py==4.2.0
MarkupSafe==3.0.4
mdurl==0.1.2
packaging==26.3
pluggy==1.7.0
Pygments==2.21.0
pytest==9.1.1
rich==15.0.0
shellingham==1.5.4
smmap==5.0.3
typer==0.27.3
```

`requirements.txt` and `pyproject.toml` use minimum versions (`>=`), so a
fresh install may resolve newer versions than these.

## Baseline commands and results

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
bash scripts/setup_demo_app.sh
pytest -q
agentproof audit --repo ./demo-app --base main --branch ai-fix \
  --task "Fix password reset token handling"
```

| Check | Result |
|-------|--------|
| `pytest -q` | 42 passed |
| Demo audit risk score | 90/100 |
| Demo audit recommendation | REJECT (exit code 1) |
| Demo audit findings | 5: 1 critical (SECRET001), 2 high (AUTH001), 2 medium (TESTCOV001, SCOPE001) |
