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

`demo-app/` is a tiny two-branch Git repository used to exercise the
rules. It is not committed; build it with:

```bash
bash scripts/setup_demo_app.sh
```

It contains:

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

This prints a terminal report. The command exits with status `1` when the
recommendation is `reject`, so it can be wired into CI. See "Output
formats" for HTML, JSON and SARIF.

AgentProof audits the changes `--branch` made since it diverged from
`--base` (git's three-dot diff, `base...branch`), the same view as a pull
request's "Files changed" tab. Commits added to the base afterwards are not
reported as changes made by the branch.

## Expected audit output

Auditing `ai-fix` against `main` should surface four findings and a risk
score of 70/100, recommending **REJECT**:

| Severity | Rule       | Location                | Issue                                                   |
|----------|------------|-------------------------|---------------------------------------------------------|
| CRITICAL | SECRET001  | backend/utils.py:7      | Hardcoded key, shown redacted as `api_key = "sk-1****"` |
| HIGH     | AUTH001    | backend/auth.py:57-58   | Deleted `if is_expired(token): raise ValueError(...)`   |
| MEDIUM   | TESTCOV001 | (both files)            | Production code changed, no test file changed           |
| MEDIUM   | SCOPE001   | backend/utils.py        | Change unrelated to the stated task                     |

The two deleted lines of the expiry check are one removed `if` block, so
they are reported and scored as one AUTH001 finding (see "Finding
grouping" below).

Auditing `main` against itself (or a genuinely safe branch) produces no
findings and a risk score of 0, recommending **APPROVE**.

## Output formats

```bash
agentproof audit --repo . --base main --branch feature                       # terminal (default)
agentproof audit --repo . --base main --branch feature --format json > report.json
agentproof audit --repo . --base main --branch feature --output report.html  # format from extension
agentproof audit --repo . --base main --branch feature --format sarif --output agentproof.sarif
```

- `--format` is `terminal` (default), `html`, `json` or `sarif`. If it is
  omitted and `--output` ends in `.html`/`.htm`, `.json` or `.sarif`, the
  format is taken from the extension; any other extension means terminal.
- The report goes to standard output unless `--output PATH` is given.
- Status messages ("report written to ...") and errors always go to
  standard error, so standard output contains only the report and
  `--format json` output can be piped straight into other tools.
- Every format applies the same secret redaction.

Exit codes: `0` approve or review, `1` reject, `2` usage, configuration,
git or file-writing errors.

**Change from earlier versions:** the CLI used to print the terminal report
*and* always write `agentproof-report.html` (or the `--output` path) as
HTML. It now produces one report per run. `--output report.html` still
produces HTML because the format is inferred from the extension, but
running without `--output` no longer creates an HTML file.

**Line numbers.** Added lines are numbered as in the audited branch.
Deleted lines can only be numbered as in the base version, so they are
labelled, for example `backend/auth.py:57-58 (deleted, base line numbers)`.
JSON gives each finding a `side` (`"new"`, `"old"` or `null` for
whole-file findings) plus `line_number`/`end_line_number`.

**SARIF 2.1.0.** Severities map to SARIF levels (critical/high → `error`,
medium → `warning`, low → `note`; the original severity is kept in
`properties.severity`). Paths are repository-relative. Deleted-line
findings point at the file without a line region, because their line
numbers belong to the base version, not the current file; the base line
numbers are stated in the message and in `properties.baseStartLine` /
`baseEndLine`. Findings silenced by an ignore directive are included with
an `inSource` suppression. The output is validated in the test suite
against the official OASIS SARIF 2.1.0 schema (see "Running the tests").

## GitHub Action

This repository is also a reusable GitHub Action (`action.yml`). The short
form of the step is:

```yaml
- uses: Dhruvshetty225/agentproof@<commit-sha>
  with:
    task: ${{ github.event.pull_request.title }}
```

That step alone is not a working workflow. It also needs a `pull_request`
trigger, a checkout with full history, permissions, and steps to upload the
report. A complete workflow is in
[`examples/agentproof-pull-request.yml`](examples/agentproof-pull-request.yml):

```yaml
name: AgentProof
on:
  pull_request:
    branches: [main]
permissions:
  contents: read
jobs:
  audit:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write   # only for the optional code scanning upload
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0              # needed to find the merge base
          persist-credentials: false  # the audit never pushes
      - id: agentproof
        uses: Dhruvshetty225/agentproof@<commit-sha>
        with:
          task: ${{ github.event.pull_request.title }}
          format: sarif
          output: agentproof.sarif
      - if: ${{ !cancelled() }}
        uses: actions/upload-artifact@v7
        with:
          name: agentproof-report
          path: agentproof.sarif
      - if: ${{ !cancelled() && github.event.pull_request.head.repo.full_name == github.repository }}
        uses: github/codeql-action/upload-sarif@v4
        with:
          sarif_file: agentproof.sarif
          category: agentproof
```

Inputs: `base`/`head` (default: the pull request's base and head commits),
`task`, `format` (default `sarif`), `output` (default `agentproof.sarif`),
`config`, `fail-on-reject` (default `true`), `python-version`. Outputs:
`exit-code` and `report`.

How it handles the security-sensitive parts:

- **No untrusted code runs.** AgentProof is installed from the action's own
  source, not from the pull request, and only reads git data. Use the
  action by a pinned commit of this repository, not `uses: ./` from the
  repository being audited.
- **Leave `config` empty for untrusted pull requests.** By default the
  configuration is `.agentproof.toml` on the base commit, which the pull
  request cannot change. If `config` points at a file inside the checked-out
  repository, that file comes from the pull request itself, so the pull
  request could disable rules or raise the thresholds to pass its own
  audit. Only set `config` to a file the pull request cannot modify.
- **`pull_request`, never `pull_request_target`.** On `pull_request`, fork
  pull requests run with a read-only token and no secrets.
- **No shell injection from pull request text.** Inputs such as the pull
  request title are passed to the shell only through environment
  variables.
- **History:** `fetch-depth: 0` is required; with a shallow checkout the
  merge base cannot be found and the action fails with exit code 2.
- **Report upload:** the artifact upload works for every repository. The
  code scanning upload is optional and skipped for fork pull requests,
  whose token cannot write security events.

Account-dependent limits (from GitHub's documentation; check the current
billing pages before relying on them):

- GitHub Actions is free for public repositories on standard GitHub-hosted
  runners. Private repositories use the plan's monthly included minutes
  and artifact storage (for example 2,000 minutes and 500 MB on GitHub
  Free); what happens beyond that depends on your account's billing
  settings.
- Uploading SARIF to code scanning in a private repository requires GitHub
  Code Security or GitHub Advanced Security, which are paid products. Drop
  that step if you don't have them; the artifact upload still works.

Nothing here runs automatically in this repository: the example lives in
`examples/`, not `.github/workflows/`, and the action has not been run on
GitHub-hosted runners as part of this work.

## Configuration

AgentProof works without any configuration. To change its behavior, add an
optional `.agentproof.toml`:

```toml
[rules]
disable = ["SCOPE001"]        # rules that do not run at all

[severity]
TESTCOV001 = "low"            # low | medium | high | critical

[thresholds]
review = 40                   # score >= review -> REVIEW
reject = 70                   # score >= reject -> REJECT
```

Every section and key is optional. Which file is used (the first match
wins; files are never merged):

1. `--config PATH` on the command line.
2. `.agentproof.toml` at the root of the **base** branch, read through git.
   It is read from the base, not from the branch being audited, so a change
   cannot relax its own audit by editing the file.
3. Built-in defaults: all rules on, built-in severities, review at 30,
   reject at 60.

Unknown sections or keys, unknown rule IDs, invalid severities, and
thresholds that are not whole numbers from 1 to 100 with review below
reject are reported as a configuration error (exit code 2) instead of being
ignored. The report shows which configuration was used.

## Ignoring a specific finding

Add `agentproof: ignore[RULE_ID]` to a line, usually in a comment:

```python
DEFAULT_TOKEN = "placeholder"  # agentproof: ignore[SECRET001]
```

- Several rules can be listed: `agentproof: ignore[AUTH001, LOG001]`.
- A directive only applies to findings on the same line. For an added
  line, it must be on that added line. For a deleted line, it must be on
  the deleted line itself, which means it was already in the base version:
  a change cannot silence a finding about code it deletes.
- Findings without a line (TESTCOV001, SCOPE001, UNREVIEWABLE001) cannot be
  ignored inline; disable the rule in `.agentproof.toml` instead.
- Malformed directives (`ignore`, `ignore[]`, lowercase IDs, trailing
  commas) have no effect.
- Ignored findings are not scored, but the report still lists them.

## Secret redaction

Terminal and HTML reports never show a full detected secret. A value keeps
its first four characters followed by `****` (`sk-1234secret` ->
`sk-1****`); values of four characters or fewer become `****`. The body of
a PEM private key is always replaced with `****`. A secret found on one line
is also masked wherever the same value appears in another finding.

## Finding grouping

When a whole block is deleted, AUTH001 would otherwise flag every line of
it. Deleted-line findings from the same rule and file are merged when they
belong to one removed statement: a flagged line plus the contiguous deleted
lines indented deeper than it (its body or continuation lines). A line at
the same or shallower indentation starts a new statement, so two adjacent
but independent checks are still reported and scored separately.

## Project architecture

```
agentproof/
  cli.py       Typer CLI — `agentproof audit ...`
  diff_parser.py  Parses `git diff -U0` between base and branch into
                   per-file added/deleted lines with line numbers
  schema.py    Finding / AuditReport dataclasses, Severity and
               MergeRecommendation enums
  engine.py    Runs all rules, deduplicates findings, applies ignores,
               grouping and config, scores risk, and produces the
               final AuditReport
  config.py    Loads and validates the optional .agentproof.toml
  ignores.py   Inline "agentproof: ignore[RULE_ID]" directives
  grouping.py  Merges findings from one deleted block
  redaction.py Masks secrets before any report is displayed or written
  report.py    Renders an AuditReport to HTML via Jinja2
  identifiers.py  Splits snake_case/camelCase names into words so rules
                  match whole words instead of raw substrings
  rules/
    auth.py             deleted auth/permission/verify/csrf/token-expiry
                        checks, including security decorators
    secrets.py          hardcoded credentials (db_password = "..."), sk-,
                        AWS, GitHub and Slack token shapes, PEM private keys
    logging_safety.py   sensitive values passed to print/logging calls
    test_coverage.py    production changes with no test-file changes
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
medium = 10, low = 5 points per finding (after grouping), summed and
capped at 100. By default 0–29 → approve, 30–59 → review, 60–100 → reject;
the thresholds can be changed in `.agentproof.toml`.

## Future roadmap

- Support additional languages beyond Python (JS/TS, Go) in the rule set.
- Post the report as a pull request comment from the GitHub Action.
- Richer `unrelated_changes` scoping using commit message / PR description
  instead of a single `--task` string.

## Known Limitations

AgentProof is a local-first, rule-based auditor — it's designed to catch
common patterns of risky AI-generated changes, not to replace human code
review.

- **`unrelated_changes` (SCOPE001)** uses keyword matching against the task
  description, not semantic understanding. It can still miss genuinely
  related files whose code doesn't contain the literal task keywords (or
  any close variant of them) — that's an inherent limit of keyword
  matching, not something a regex fix can close. It now compares whole,
  normalized words instead of raw substrings, so it no longer flags
  unrelated files that merely share a substring with a keyword (e.g.
  "tokenizer" vs. "token") and correctly matches simple plurals (e.g.
  "tokens" vs. "token"). Treat its findings as a prompt to double-check,
  not a definitive verdict.
- **Deleted security checks (AUTH001)** match whole words of names, so
  `is_authorized`, `isAuthorized` and `@require_role("admin")` are caught
  while `author` and `tokenizer` are not. It still works line by line: it
  reports that security-relevant code was deleted, not whether the deletion
  weakens security (removing `@csrf_exempt` is flagged too). Comment-only
  lines are skipped, but a trailing comment on a code line still counts,
  and `#` lines such as C `#define` are treated as comments. Negated or
  differently named checks (`unauthorized`, `is_staff`) are not in the word
  list.
- **Secret detection (SECRET001)** catches credential-named fields assigned
  a quoted literal (`db_password = "..."`, `"api_key": "..."`) and the token
  shapes it knows (`sk-`, AWS `AKIA...`, GitHub `ghp_/gho_/ghs_`, Slack
  `xox[baprs]-`, PEM private-key headers). It still won't catch secrets
  split across multiple lines, built via string concatenation,
  base64-encoded, assigned without quotes (unquoted YAML scalars), held in
  oddly named fields, or in other providers' formats. A quoted placeholder
  such as `"${DB_PASSWORD}"` is still reported as a hardcoded value.
- **Logging safety (LOG001)** ignores words inside static messages
  (`logger.info("Reset token sent")`) and looks at the logged values:
  arguments, f-string/template placeholders and quoted lookup keys. It only
  sees a value through its name, so `logger.info(f"password={pw}")` is not
  flagged, while `logger.info(mask(token))` still is. It checks one line at
  a time, so log calls split over several lines are missed, and it
  recognizes `print(...)` and `log`/`logger`/`logging` calls, not
  `console.log`.
- **Test coverage (TESTCOV001)** only detects whether a file that *looks
  like* a test changed (`tests/`, `test_*.py`, `conftest.py`, `*.test.ts`,
  `*Test.java`, `*_test.go`, ...). It does not measure coverage. Any
  changed test file suppresses the warning, even an unrelated test or a
  test file that was deleted. `*.test.jsx`/`*.test.tsx` names are not
  recognized.
- **SARIF locations for deleted lines** point at the file without a line,
  so code scanning cannot highlight the deleted code itself. If the whole
  file was deleted, the path no longer exists in the pull request's head.
- **The GitHub Action** has only been checked locally (YAML parsing and
  running its shell steps against the demo repository). It has not been
  run on GitHub-hosted runners.
- **Redaction** can only hide values that SECRET001 recognizes. A secret
  it does not detect is shown as-is. To stay on the safe side, a detected
  value is masked everywhere it appears as a whole word, so a very short
  or common value (e.g. `token = "abc"`) can also mask unrelated text.
- **Grouping** relies on indentation, so it assumes consistent
  indentation within a deleted block and only applies to deleted lines.
- **Ignore directives** are plain text: AgentProof does not check that a
  directive is inside a comment.

## Running the tests

```bash
bash scripts/setup_demo_app.sh     # builds the demo-app fixture
bash scripts/fetch_sarif_schema.sh # downloads the SARIF 2.1.0 schema (pinned, checksum-verified)
pytest -v
```

The SARIF schema is published by OASIS under its IPR policy rather than an
open-source license, so it is downloaded instead of committed. Without it,
the schema-validation tests are reported as **skipped** ("SARIF schema
validation was NOT performed"), not as passed.

## Testing and Hardening

AgentProof was deliberately stress-tested rather than taken at face
value. Several real bugs surfaced during that process:

1. A packaging bug that caused the HTML report to crash on a normal
   (non-editable) install — only worked in local dev mode.
2. A blind spot where binary file swaps and pure renames (no content diff)
   were silently invisible to every rule, letting exactly the kind of
   sneaky change this tool exists to catch sail through as a clean
   APPROVE.
3. `unrelated_changes` (SCOPE001) used raw substring matching, so a
   keyword like "token" could match inside an unrelated word like
   "tokenizer" — a false negative, since a file that should have looked
   unrelated didn't get flagged.
4. `secrets` (SECRET001) missed quoted-key config formats like JSON
   (`"api_key": "..."`), only catching Python/JS-style unquoted-key
   assignments.

All four were caught by running the tool against a real, unrelated repo
instead of just the bundled demo, and all are now fixed and covered by
regression tests (42/42 passing). The takeaway: a tool is only as
trustworthy as the testing behind it, which is why AgentProof's own code
gets the same scrutiny it applies to yours.
