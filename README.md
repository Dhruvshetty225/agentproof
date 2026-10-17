# AgentProof

AgentProof is a local-first CLI that audits AI-generated code changes before
merge. It compares two Git branches, detects risky changes with rule-based
checks, calculates a merge risk score, and writes a terminal, HTML, JSON or
SARIF report. An optional local LLM verifier (Ollama) can give a second
opinion on each finding.

It was evaluated on 78 real pull requests opened by AI coding agents and 20
synthetic cases; see [Evaluation](#evaluation) and
[`docs/REPORT.md`](docs/REPORT.md).

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

None of these risks is specific to AI-written code: people make the same
mistakes, and AgentProof works on any branch. In the evaluation's 78
agent-authored pull requests, the human-reviewed labels found 24 behavior
changes without tests and 4 unrelated changes, and no removed security
check, hardcoded secret or logged secret.

## Installation

Everything runs locally, and every dependency is free and open source.
AgentProof needs git and Python. `pyproject.toml` declares Python 3.9 or
later, but only some of those versions were actually tested:

- **Tested on GitHub:** the Tests workflow (`.github/workflows/tests.yml`)
  passed on Python 3.10, 3.11 and 3.12 (Ubuntu) at commit `36eb6b2`:
  [run 38996141338](https://github.com/Dhruvshetty225/agentproof/actions/runs/38996141338).
- **Tested locally:** the full test suite on Python 3.12 (macOS).
- **Not tested:** 3.9. Every source file passes a 3.9 syntax check, nothing
  more.

```bash
git clone <this-repo>
cd agentproof
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

This installs the `agentproof` command via the `agentproof` console-script
entry point defined in `pyproject.toml`. The runtime dependencies are
typer, GitPython, Jinja2 and rich. `pip install -r requirements.txt` also
installs:

- pytest and jsonschema, for the tests;
- matplotlib, for the evaluation charts.

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
  whose token cannot write security events. If the report file cannot be
  written, the action fails with exit code 2 rather than uploading nothing
  silently.
- **Not a tamper-resistant security gate.** The pull request controls the
  ignore directives on the lines it adds. It can silence those findings and
  still pass `fail-on-reject` (see
  [Ignoring a specific finding](#ignoring-a-specific-finding)).
  It can also add a `.gitattributes` file that marks source files as
  binary (for example `*.py -diff`), which hides their lines from the
  rules. Documenting this does not prevent it. With the current
  configuration, treat the result as review assistance, and check the
  ignored findings (SARIF suppressions) and any `.gitattributes` changes in
  every review.

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

This repository runs the action on its own pull requests to `main`, with
`.github/workflows/agentproof.yml` (the example above, pinned to commit
`7828f89` of this repository). Its first run on a GitHub-hosted runner was
test pull request
[#1](https://github.com/Dhruvshetty225/agentproof/pull/1)
([run 39000721919](https://github.com/Dhruvshetty225/agentproof/actions/runs/39000721919)):
it installed AgentProof, audited the pull request (no findings, APPROVE)
and uploaded the SARIF report as an artifact and to code scanning.

The third-party actions used here were confirmed to exist with a read-only
`git ls-remote` on 2026-10-17:

- `actions/checkout@v7`
- `actions/setup-python@v7`
- `actions/upload-artifact@v7`
- `github/codeql-action/upload-sarif@v4`

They are pinned by tag, not by commit SHA, so what a tag points to can
change.

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
- **Not a security boundary for added lines.** A directive on an added line
  comes from the change being audited. A change can add, for example, a
  hardcoded secret together with `# agentproof: ignore[SECRET001]` on the
  same line. The finding then moves to the ignored list, is not scored,
  and the change can still get APPROVE and exit code 0; this was confirmed
  in testing. Documenting it does not prevent it. When auditing untrusted
  changes, always read the ignored findings in the report.
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

## Optional local LLM verifier

`--llm-verify` asks a local Ollama model whether each finding is actually
risky. It is off by default.

- **When a finding is removed.** Only when the model clearly answers "no".
  The model can never add findings.
- **When the model is not asked.** Critical findings, and text that seems to
  address an AI model, are always kept.
- **Failures.** On a timeout, a malformed reply or Ollama not running, the
  finding is kept and the report says so.
- **Local only.** Only a server on this machine is accepted; there is no
  cloud fallback.

Setup, from [`docs/LLM_VERIFIER.md`](docs/LLM_VERIFIER.md). Ollama is free
(MIT license); a model download is 1–5 GB.

```bash
brew install ollama
ollama serve                       # in its own terminal
ollama pull qwen2.5-coder:1.5b     # 986 MB; the default qwen2.5-coder:7b is 4.7 GB
agentproof audit --repo . --branch feature --task "..." --llm-verify --llm-model qwen2.5-coder:1.5b
```

**Measured effect: none so far.** With `qwen2.5-coder:1.5b`, the verifier
suppressed no findings, so its results equal the rules'. The 7B model froze
the 8 GB test machine during its full run. See
[Evaluation](#evaluation).

## Evaluation

The evaluation dataset, labels and code are in [`eval/`](eval/README.md).
The full write-up is [`docs/REPORT.md`](docs/REPORT.md). Every number below
comes from these commands:

```bash
python -m eval.summarize_dataset                       # dataset and label counts
GITHUB_TOKEN=... python -m eval.collect --from-manifest eval/manifest.csv   # re-download the real diffs
python -m eval.run_eval                                # original vs improved rules -> eval/results/
python -m eval.run_llm_eval --model qwen2.5-coder:1.5b # rules vs LLM only vs hybrid -> eval/results/llm/
```

**Dataset:**

- 78 merged pull requests opened by five AI coding agents in 66 public
  repositories;
- 20 hand-written synthetic cases;
- every label reviewed by a human.

**Results per case**, measured as "any finding" against the human label
(precision / recall / F1). These come from `eval/results/comparison.md` and
`eval/results/llm/comparison.md`.

| Cases | Original rules | Improved rules |
|---|---|---|
| Real, all 78 | 0.51 / 0.89 / 0.65 | 0.60 / 0.93 / 0.72 |
| Real, held-out 40 (never used for tuning) | 0.44 / 0.85 / 0.58 | 0.52 / 0.85 / 0.65 |
| Synthetic 20 | 0.75 / 0.82 / 0.78 | 1.00 / 1.00 / 1.00 |

What changed with the improved rules:

- **TESTCOV001** false positives on real cases fell from 20 to 9.
- **AUTH001 and SECRET001** false positives rose from 6 to 9 and from 2 to 3.
- **Real security positives:** there are none, so security recall was
  measured only on the synthetic cases, where it went from 0.43 to 1.00.
- **Scoring:** the default scoring reached "review" or "reject" on only 2 of
  the 27 risky real cases (recall 0.07).

LLM comparison, on the 96 cases where every mode produced a result
(`qwen2.5-coder:1.5b`):

| Mode | Real, all 76 | Synthetic 20 | Time per real case |
|---|---|---|---|
| Rules only | 0.61 / 0.93 / 0.74 | 1.00 / 1.00 / 1.00 | 0.00 s |
| LLM only | 0.36 / 1.00 / 0.52 | 0.55 / 1.00 / 0.71 | 4.82 s |
| Hybrid (rules + verifier) | 0.61 / 0.93 / 0.74 | 1.00 / 1.00 / 1.00 | 2.28 s |

Two of these results are not what they look like:

- **LLM only reported a risk on every case,** so its recall of 1.00 is not
  good detection.
- **The hybrid's model answered "risky" every time,** so it removed nothing.

The benchmark saved each model call's parsed status and one-sentence
reason, not the model's raw reply. The parsed decisions can be recomputed
and checked from `eval/results/llm/`; the exact original replies cannot.

## Project architecture

```
agentproof/
  cli.py       Typer CLI — `agentproof audit ...`
  diff_parser.py  Parses `git diff -U0` between base and branch into
                   per-file added/deleted lines with line numbers
  schema.py    Finding / AuditReport dataclasses, Severity and
               MergeRecommendation enums
  engine.py    Runs all rules, deduplicates findings, applies ignores,
               grouping, config and the optional LLM verifier, scores
               risk, and produces the final AuditReport
  config.py    Loads and validates the optional .agentproof.toml
  ignores.py   Inline "agentproof: ignore[RULE_ID]" directives
  grouping.py  Merges findings from one deleted block
  redaction.py Masks secrets before any report is displayed or written
  report.py    Renders an AuditReport to HTML (Jinja2) or JSON
  sarif.py     Renders an AuditReport as SARIF 2.1.0
  llm_verify.py  Optional local Ollama verifier (--llm-verify)
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
eval/          Evaluation dataset (manifest, labels, synthetic cases),
               collector, metrics and runners; results in eval/results/
docs/          REPORT.md (evaluation), LLM_VERIFIER.md, BASELINE.md
tests/         pytest suite covering the diff parser, each rule, the
               end-to-end engine/CLI behavior, the outputs and the evaluation
               code
```

**Risk scoring** (`agentproof/engine.py`): critical = 30, high = 20,
medium = 10, low = 5 points per finding (after grouping), summed and
capped at 100. By default 0–29 → approve, 30–59 → review, 60–100 → reject;
the thresholds can be changed in `.agentproof.toml`.

## Future work

The evaluation measured the rules as built. These items are outside this
project's scope: each would change the measured results, or needs data or
hardware the project did not have (see
[docs/REPORT.md, section 9](docs/REPORT.md#9-future-work)).

- Support additional languages beyond Python (JS/TS, Go) in the rule set.
- Post the report as a pull request comment from the GitHub Action.
- **Reduce the false positives found in the evaluation,** with a new
  tuning round on the development split only:
  - skip lockfiles and documentation in AUTH001;
  - handle fake values in test files in SECRET001;
  - require more than one shared word in SCOPE001;
  - recognize `.vue` and similar files in TESTCOV001.
- Revisit the default severities and thresholds: only 2 of the 27 risky
  real cases reach "review" today.
- Measure a larger local model on a machine with more than 8 GB of memory.

## Known Limitations

AgentProof is a local-first, rule-based auditor — it's designed to catch
common patterns of risky AI-generated changes, not to replace human code
review. **A clean audit does not prove a change is safe.** It only means
none of the six patterns was found in the diff's text.

- **Measured on real pull requests** (see [Evaluation](#evaluation)):
  - the security rules raised false alarms on lockfiles, documentation,
    data and fake test values;
  - SCOPE001 found 1 of 4 real scope problems;
  - the default score reached "review" for only 2 of 27 risky real cases.

  The evaluation has no real security positives, so how many real
  security problems the rules catch is unknown.
- **The optional LLM verifier** can only remove findings, never add any.
  With the small model it was tested with, it removed none. Its
  prompt-injection check is a simple heuristic.

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
  differently named checks (`unauthorized`, `is_staff`, `is_verified`) are
  not in the word list.

  Only `#`, `//` and `/*` comments are skipped. SQL or Lua `--`,
  HTML/Markdown `<!-- -->` and batch `@rem` comments still count, and so do
  words inside strings, Markdown prose and lockfiles. These produced most
  of its false alarms in the evaluation.
- **Secret detection (SECRET001)** catches credential-named fields assigned
  a quoted literal (`db_password = "..."`, `"api_key": "..."`) and the token
  shapes it knows (`sk-`, AWS `AKIA...`, GitHub `ghp_/gho_/ghs_`, Slack
  `xox[baprs]-`, PEM private-key headers). It still won't catch secrets
  split across multiple lines, built via string concatenation,
  base64-encoded, assigned without quotes (unquoted YAML scalars), held in
  oddly named fields, or in other providers' formats. A quoted placeholder
  such as `"${DB_PASSWORD}"` is still reported as a hardcoded value.

  Confirmed misses:
  - names that don't end in password, secret, token or api key, such as
    `aws_secret_access_key` and `private_key`;
  - type-annotated assignments (`password: str = "..."`);
  - Go's `:=`;
  - Stripe-style `sk_live_...` keys;
  - `sk-` keys with fewer than four letters or digits before the first
    hyphen, such as `sk-ant-...`.
- **Logging safety (LOG001)** ignores words inside static messages
  (`logger.info("Reset token sent")`) and looks at the logged values:
  arguments, f-string/template placeholders and quoted lookup keys. It only
  sees a value through its name, so `logger.info(f"password={pw}")` is not
  flagged, while `logger.info(mask(token))` still is. It checks one line at
  a time, so log calls split over several lines are missed, and it
  recognizes `print(...)` and `log`/`logger`/`logging` calls, not
  `console.log`. A sensitive name anywhere after the log call on the same
  line counts, even in a separate statement (`print("ok"); password = x`).
- **Test coverage (TESTCOV001)** only detects whether a file that *looks
  like* a test changed (`tests/`, `test_*.py`, `conftest.py`, `*.test.ts`,
  `*Test.java`, `*_test.go`, ...). It does not measure coverage. Any
  changed test file suppresses the warning, even an unrelated test or a
  test file that was deleted. `*.test.jsx`/`*.test.tsx` names are not
  recognized, and `.vue` files are not treated as source code. Tests written
  inside a source file (Rust `#[cfg(test)]`) are not seen.
- **SARIF locations for deleted lines** point at the file without a line,
  so code scanning cannot highlight the deleted code itself. If the whole
  file was deleted, the path no longer exists in the pull request's head.
- **The GitHub Action** has run once on a GitHub-hosted runner
  ([run 39000721919](https://github.com/Dhruvshetty225/agentproof/actions/runs/39000721919)),
  on a test pull request that only added a workflow file, so it reported
  no findings. A REJECT that fails the job has only been tested locally
  (`tests/test_action.py` runs the action's shell steps), and pull
  requests from forks have not been tested.
- **Redaction** can only hide values that SECRET001 recognizes. A secret
  it does not detect is shown as-is. To stay on the safe side, a detected
  value is masked everywhere it appears as a whole word, so a very short
  or common value (e.g. `token = "abc"`) can also mask unrelated text.
- **Grouping** relies on indentation, so it assumes consistent
  indentation within a deleted block and only applies to deleted lines.
- **Ignore directives** are plain text: AgentProof does not check that a
  directive is inside a comment. A directive on an added line comes from
  the change itself and can silence that line's findings, so AgentProof is
  not a tamper-resistant security gate (see
  [Ignoring a specific finding](#ignoring-a-specific-finding)).
- **`.gitattributes` comes from the checked-out files.** A change that adds
  `*.py -diff` makes git report its Python files as binary, so AUTH001,
  SECRET001 and LOG001 never see their lines. Only UNREVIEWABLE001
  (medium) fires, and in testing such a change, which also deleted an
  auth check, was approved. Git 2.40's `--attr-source` could read the
  attributes from the base instead; AgentProof does not use it yet.
- **Unusual file names.** Git quotes file names that contain non-ASCII or
  special characters (for example `"b/caf\303\251.py"`), and AgentProof
  keeps the quoted form. Such paths are shown wrongly, and TESTCOV001 does
  not treat them as source files.
- **Mode-only changes** (for example making a file executable) change no
  lines, so no rule sees them.
- **Python versions:** tested on 3.10, 3.11 and 3.12. 3.9 is declared in
  `pyproject.toml` but untested (see Installation).

## Running the tests

```bash
bash scripts/setup_demo_app.sh     # builds the demo-app fixture
bash scripts/fetch_sarif_schema.sh # downloads the SARIF 2.1.0 schema (pinned, checksum-verified)
pytest -v
```

Some tests are skipped unless their prerequisites are met:

- The LLM tests use a fake model and a fake Ollama server.
- One optional test talks to a real local Ollama. It is skipped unless
  `AGENTPROOF_OLLAMA_SMOKE=1` is set.
- The tests never need the real pull-request diffs; only `python -m
  eval.run_eval` and `python -m eval.run_llm_eval` read `eval/data/real/`.

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
regression tests (42/42 passing at the time; the suite has since grown,
see "Running the tests"). The takeaway: a tool is only as
trustworthy as the testing behind it, which is why AgentProof's own code
gets the same scrutiny it applies to yours.
