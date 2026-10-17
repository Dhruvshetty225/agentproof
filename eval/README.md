# AgentProof Evaluation Dataset

This folder holds the data used to evaluate AgentProof's rules:

- **78 real pull requests** authored by AI coding agents on public GitHub;
- **20 synthetic cases**, written by hand to exercise each rule;
- **human-reviewed labels** for every case: tentative labels were drafted
  first, then a human reviewer confirmed or corrected every row.

Every number below is printed by:

```bash
python -m eval.summarize_dataset
```

That command only reads committed files (`manifest.csv`,
`collection_report.json`, `labels.csv`).

## Files

| File | What it is | Committed? |
|------|------------|------------|
| `agents.py` | The AI-agent GitHub Apps whose PRs count as AI-authored | yes |
| `github_api.py` | Read-only GitHub REST client (rate limits, retries, pagination) | yes |
| `collect.py` | Collector: search, filter, download, resume, re-fetch | yes |
| `manifest.csv` | One row per real case: URL, repository, PR number, agent, title, pinned base/head commits, diff SHA-256, collection time | yes |
| `collection_report.json` | Totals and exclusions for the final collection run | yes |
| `collection_report_run1.json` | Report of the first run (12 per agent), kept for transparency | yes |
| `make_synthetic.py`, `synthetic/` | The 20 synthetic cases and the script that generates them | yes |
| `labels.csv` | Reviewed labels (each row `confirmed` or `corrected`) | yes |
| `LABELING_GUIDE.md` | Definition of "risky" for each rule | yes |
| `split.py`, `split.csv` | Fixed development / held-out split, made before any result | yes |
| `u0.py` | Converts the context diffs to git's `-U0` form that AgentProof parses | yes |
| `metrics.py` | Precision, recall, F1 and counts per rule and per case | yes |
| `run_rules.py` | Adapter that runs one AgentProof version on the prepared diffs | yes |
| `run_eval.py` | Runs the original and improved versions and writes `results/` | yes |
| `results/` | Metrics, predictions, comparison table, charts, environment | yes |
| `run_llm_eval.py`, `results/llm/` | Rules only vs LLM only vs hybrid with a local Ollama model; run with `qwen2.5-coder:1.5b` (see `docs/LLM_VERIFIER.md`) | yes |
| `data/real/<case_id>/` | `metadata.json` (incl. PR description) and `pr.diff` for each real case | **no** (see below) |

The real diffs and PR descriptions are third-party content under many
different licenses (or none), so they are not committed. `manifest.csv`
pins every case to exact commits and a checksum, so anyone can download
the same data again and verify it.

## How the real cases were collected

**Evidence of AI involvement.** A PR counts only if its author is the bot
account of one of these GitHub Apps and the API reports the author as
`type: "Bot"` with the expected login and ID. App bot accounts can only be
operated by their app, so this is verifiable, unlike a label that a human
adds. Each app was checked on 2026-10-16 with `GET /users/<slug>[bot]` and
`GET /apps/<slug>`:

| App slug | Bot login | App owner | Product |
|----------|-----------|-----------|---------|
| `copilot-swe-agent` | `Copilot` | github | GitHub Copilot coding agent |
| `devin-ai-integration` | `devin-ai-integration[bot]` | usacognition | Devin |
| `google-labs-jules` | `google-labs-jules[bot]` | google-labs-code | Jules |
| `cursor` | `cursor[bot]` | cursor | Cursor background agent |
| `claude` | `claude[bot]` | anthropics | Claude Code |
| `amazon-q-developer` | `amazon-q-developer[bot]` | Amazon-Q-Developer | Amazon Q Developer |
| `codegen-sh` | `codegen-sh[bot]` | codegen-sh | Codegen |

`chatgpt-codex-connector` was left out: it had authored only 4 public PRs,
because Codex PRs are normally opened under the user's own account.

**Selection** (settings recorded in `collection_report.json`):

1. Search `is:pr is:public is:merged author:app/<slug> created:2026-07-01..2026-09-30`,
   oldest first, up to 10 pages (GitHub returns at most 1,000 results).
2. Skip forks, archived repositories and repositories with fewer than 10
   stars.
3. Skip PRs with more than 50 changed files or more than 1,500 changed lines.
4. Take at most 2 PRs per repository and 18 per agent.
5. Download the diff for the PR's pinned commits
   (`/compare/<base_sha>...<head_sha>`) and reject it if it is larger than
   1 MB or if its +/- line counts differ from GitHub's additions/deletions
   (a truncated or changed diff).

**Totals** (from `python -m eval.summarize_dataset`):

| | Count |
|---|---|
| Candidate PRs examined | 1,846 |
| Collected | 78 |
| Excluded: repository below 10 stars | 1,630 |
| Excluded: fork | 59 |
| Excluded: per-repository cap reached | 56 |
| Excluded: archived repository | 18 |
| Excluded: more than 1,500 changed lines | 3 |
| Excluded: more than 50 files | 2 |
| Excluded: diff truncated or mismatched | 0 |
| Duplicate search results | 0 |
| Rate-limit waits | 0 |

| Agent | Candidates examined | Collected |
|-------|---------------------|-----------|
| GitHub Copilot coding agent | 132 | 18 |
| Devin | 469 | 18 |
| Cursor | 68 | 18 |
| Claude Code | 60 | 18 |
| Jules | 1,000 (search cap) | 6 |
| Amazon Q Developer | 117 | 0 |
| Codegen | 0 | 0 |

The 78 cases come from 66 repositories, with at most 2 from any one
repository.

The collection was run twice: first with 12 PRs per agent (54 cases), then
with 18 per agent to reach the 60-100 target. The second run resumed from
the first (already-collected cases were not downloaded again), so
`collection_report.json` covers every candidate examined.

## Reproducing the data

A token with read access to public repositories is needed. It is read from
`GITHUB_TOKEN` and is never printed or saved.

```bash
# Re-download exactly the 78 pinned cases and verify every diff checksum:
GITHUB_TOKEN=... python -m eval.collect --from-manifest eval/manifest.csv

# Or repeat the whole search (results can differ as GitHub data changes):
GITHUB_TOKEN=... python -m eval.collect --per-agent 18
```

On macOS with the python.org installer, Python may not find the system
certificates (`CERTIFICATE_VERIFY_FAILED`). Run it with
`SSL_CERT_FILE=/etc/ssl/cert.pem`; certificates are still verified.

The synthetic cases are rebuilt with `python -m eval.make_synthetic`, and a
test checks that the committed files match the generator exactly.

## Synthetic cases

The 20 cases in `synthetic/` (`syn-01` ... `syn-20`) were written by hand
for this project. They are clearly marked (`kind: "synthetic"`,
`source_url: synthetic:<id>`) and must always be reported separately from
the real cases. They cover all six rules with positive and negative
examples:

| Rule | Positive cases | Negative cases |
|------|----------------|----------------|
| AUTH001 | syn-01, 02, 03 | syn-04, 05 |
| SECRET001 | syn-06, 07 | syn-08, 09 |
| LOG001 | syn-10, 11 | syn-12 |
| TESTCOV001 | syn-13 | syn-14, 15 |
| SCOPE001 | syn-16 | syn-17 |
| UNREVIEWABLE001 | syn-18, 19 | (all others) |
| none | | syn-20 (clean change) |

When a case adds a test, the test calls the code the case changes and
makes meaningful assertions about it, so on reading it counts as a test of
that change under the labeling guide. These embedded tests have **not been
executed**. Several synthetic source files are fragments (for example they
use `logger` without defining it), so the tests are not expected to run as
written. The project's own tests (`tests/test_eval_synthetic.py`) only
check that the committed files match the generator; they do not show that
the embedded tests run or pass.

They were designed with knowledge of how the rules work, so they show
whether the rules behave as intended. They do not show how well the rules
work on real code.

## Labels

`labels.csv` has one row per case:
`case_id, source_url, is_risky, risky_rule_ids, notes, review_status`.
The meaning of each rule's risk is defined in
[`LABELING_GUIDE.md`](LABELING_GUIDE.md).

**How the labels were made.** Tentative labels were first drafted by
reading each PR's title, description and diff, *without* running AgentProof
on it first. A human reviewer then went through every row, looked at the
evidence, and set it to `confirmed` (label kept) or `corrected` (label
changed). Only `confirmed` and `corrected` rows may be used for precision,
recall or F1. Each row's `notes` explains the reasoning.

The review settled several judgment calls, which are now written into the
guide:

- the label covers the whole PR diff, including commits pushed by someone
  other than the agent;
- for TESTCOV001, only tests added or changed in the PR count, and a test
  edit must exercise the change;
- a PR whose tests cover its main change is not TESTCOV001, even if a
  smaller part is untested;
- presentation-only changes (CSS, class names, layout markup, visible text)
  do not need tests;
- behavior-preserving refactors still do;
- a PR description that is out of date but still serves the title's goal
  is not SCOPE001.

Label counts (these describe the dataset; they are not results):

| | Real (78) | Synthetic (20) |
|---|---|---|
| `is_risky = 1` | 27 | 11 |
| AUTH001 | 0 | 3 |
| SECRET001 | 0 | 2 |
| LOG001 | 0 | 2 |
| TESTCOV001 | 24 | 1 |
| SCOPE001 | 4 | 1 |
| UNREVIEWABLE001 | 0 | 2 |
| `confirmed` | 77 | 20 |
| `corrected` | 1 | 0 |
| `needs_review` | 0 | 0 |

None of the 78 real PRs has a security concern (AUTH001, SECRET001,
LOG001) after review. Recall for those rules therefore cannot be measured
on real data (there are no positive examples). The real data can still
show false positives, and the synthetic cases are the only positives for
those rules.

Some real PRs raise concerns outside the six rule categories, such as a
possible path traversal, removed supply-chain pinning or deleted tests.
These are described in `notes` and are not counted as rule positives.

## Evaluation

```bash
python -m eval.split      # recreate eval/split.csv (committed; the same every time)
python -m eval.run_eval   # original vs improved version; writes eval/results/
```

The split puts about half of the real cases in a development set and half
in a held-out set, keeping each repository on one side; all synthetic cases
are development cases. It was committed before any result was computed.
[`results/README.md`](results/README.md) explains the results and analyzes
the failures.

## Limitations

- **Selection bias.** Only merged PRs in public repositories with 10 or
  more stars, from July to September 2026, and at most 1,500 changed lines.
  Most agent PRs are in small personal repositories that this excludes,
  and very large PRs are excluded too.
- **Uneven agents.** Jules has 6 cases because GitHub search stops at
  1,000 results and most of the earliest ones were in repositories under
  10 stars. Amazon Q has 0 (all 117 candidates were in forks or
  repositories under 10 stars) and Codegen had no merged PRs in the window.
- **Clustering.** Some repositories and organizations contribute several
  cases (for example 6 Claude Code cases from the `electron` organization,
  plus 2 from the related `electron-userland` and `electron-forge`
  organizations), so cases are not fully independent.
- **Bot authorship is not 100% AI authorship.** Humans can push commits to
  a bot's PR or edit its description before merge. The evidence shows who
  opened the PR, not who wrote every line.
- **PR descriptions can be inaccurate.** Several descriptions do not match
  their diffs (noted in `labels.csv`); SCOPE001 uses the description as the
  task, so this affects that rule.
- **One reviewer.** Every label was reviewed by one human reviewer; there
  was no second, independent reviewer, so no inter-rater agreement can be
  reported. Judgment calls (for example whether a presentation-only change
  needs tests) are documented in the guide and notes.
- **Untrusted content.** Titles, descriptions and diffs are third-party
  text. Nothing collected is executed, and text in them is treated as data,
  never as instructions.
