# AgentProof

AgentProof is a local-first CLI that audits AI-generated code changes before
merge. It compares two Git branches, detects risky changes with rule-based
checks, calculates a merge risk score, and generates terminal and HTML
reports.

## Why AI-generated code needs auditing

AI coding agents are fast and often correct, but they fail in a specific,
predictable way: they optimize for "make the immediate error go away" rather
than "preserve every invariant a human would care about." In practice that
looks like:

- Deleting a validation or expiry check because it was in the way of the fix,
  instead of fixing around it.
- Hardcoding a secret or placeholder credential while debugging, and leaving
  it in the diff.
- Touching files that are unrelated to the stated task, as a side effect of
  exploring the codebase.
- Shipping a behavior change with no updated test, because the agent wasn't
  asked to write one.

None of these show up as a syntax error or a failed type check. They show up
as a regression weeks later, or a leaked credential in git history.
AgentProof runs a fast, deterministic pass over a diff — before a human
reviewer even opens it — to catch this class of problem early.

## Installation

```bash
git clone <this-repo>
cd agentproof
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

This installs the `agentproof` command via the `agentproof` console-script
entry point defined in `pyproject.toml`.

## Running the demo

The repo ships with `demo-app/`, a tiny two-branch Git repository used to
exercise every rule:

- `main` — a safe password-reset implementation. Reset tokens are validated
  and expired tokens are correctly rejected (see `demo-app/tests/test_auth.py`).
- `ai-fix` — a simulated "AI fix" that removes the expiry check from
  `backend/auth.py`, hardcodes a fake API key in `backend/utils.py`, and
  never updates the tests.

Run the audit:

```bash
agentproof audit --repo ./demo-app --base main --branch ai-fix \
  --task "Fix password reset token handling"
```

This prints a terminal report and writes `agentproof-report.html` in the
current directory. The command exits with status `1` when the recommendation
is `reject`, so it can be wired into CI.

## Expected audit output

Auditing `ai-fix` against `main` should surface five findings and a risk
score of 90/100 (capped at 100), recommending **REJECT**:

| Severity | Rule       | File               | Issue                                             |
|----------|------------|--------------------|----------------------------------------------------|
| CRITICAL | SECRET001  | backend/utils.py   | Hardcoded `api_key = "sk-1234secret"`              |
| HIGH     | AUTH001    | backend/auth.py    | Deleted `if is_expired(token): raise ValueError(...)` |
| HIGH     | AUTH001    | backend/auth.py    | (second deleted line of the same check)            |
| MEDIUM   | TESTCOV001 | (both files)       | Production code changed, no test file changed      |
| MEDIUM   | SCOPE001   | backend/utils.py   | Change unrelated to the stated task                 |

Auditing `main` against itself (or a genuinely safe branch) produces no
findings and a risk score of 0, recommending **APPROVE**.

## Project architecture

```
agentproof/
  cli.py       Typer CLI — `agentproof audit ...`
  diff_parser.py  Parses `git diff -U0` between base and branch into
                   per-file added/deleted lines with line numbers
  schema.py    Finding / AuditReport dataclasses, Severity and
               MergeRecommendation enums
  engine.py    Runs all rules, deduplicates findings, scores risk,
               and produces the final AuditReport
  report.py    Renders an AuditReport to HTML via Jinja2
  rules/
    auth.py             deleted auth/verify/permission/token/expiry checks
    secrets.py          hardcoded api_key/password/secret/token, fake sk- keys
    logging_safety.py   unsafe logging/printing of sensitive fields
    test_coverage.py    production changes with no test changes
    unrelated_changes.py  changes that don't relate to the stated --task
    unreviewable_changes.py  binary file diffs and pure (content-free) renames
  templates/
    report.html  Jinja2 template for the HTML report (packaged with the
                 module so it ships correctly in a built wheel, not just
                 in an editable install)
demo-app/      Fixture repo with a safe `main` and a flawed `ai-fix` branch
tests/         pytest suite covering the diff parser, each rule, and the
               end-to-end engine/CLI behavior
```

**Risk scoring** (`agentproof/engine.py`): critical = 30, high = 20,
medium = 10, low = 5 points per finding, summed and capped at 100.
0–29 → approve, 30–59 → review, 60–100 → reject.

## Future roadmap

- Support additional languages beyond Python (JS/TS, Go) in the rule set.
- Pluggable rule configuration (enable/disable rules, custom severity
  thresholds via a config file).
- GitHub Action / pre-merge CI integration that posts the report as a PR
  comment.
- Richer `unrelated_changes` scoping using commit message / PR description
  instead of a single `--task` string.
- JSON output mode for machine consumption by other tooling.

## Known Limitations

AgentProof is a local-first, rule-based auditor — it's designed to catch
common patterns of risky AI-generated changes, not to replace human code
review.

- **`unrelated_changes` (SCOPE001)** uses simple keyword matching against
  the task description, not semantic understanding. It can miss genuinely
  related files whose code doesn't contain the literal task keywords, and
  can occasionally flag unrelated files that happen to share a substring
  with a task keyword. Treat its findings as a prompt to double-check, not
  a definitive verdict.
- **Secret detection** currently catches Python/JS-style assignments
  (`api_key = "..."`) but not quoted-key config formats like JSON/YAML
  (`"api_key": "..."`). Support for these formats is a planned improvement.
- **CLI and report-rendering code** (`cli.py`, `report.py`) aren't yet
  covered by the test suite — only the diff parser, rule engine, and
  scoring logic are. The tool's core logic is well-tested; the
  presentation layer isn't yet.

## Testing and Hardening

AgentProof was deliberately stress-tested rather than taken at face
value. Two real bugs surfaced during that process:

1. A packaging bug that caused the HTML report to crash on a normal
   (non-editable) install — only worked in local dev mode.
2. A blind spot where binary file swaps and pure renames (no content diff)
   were silently invisible to every rule, letting exactly the kind of
   sneaky change this tool exists to catch sail through as a clean
   APPROVE.

Both were caught by running the tool against a real, unrelated repo
instead of just the bundled demo, and both are now fixed and covered by
regression tests (36/36 passing). The takeaway: a tool is only as
trustworthy as the testing behind it, which is why AgentProof's own code
gets the same scrutiny it applies to yours.
