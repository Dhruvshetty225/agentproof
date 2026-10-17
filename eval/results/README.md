# Evaluation results

Every number on this page comes from the files in this folder, which are
written by:

```bash
python -m eval.run_eval
```

The command needs the 78 real diffs in `eval/data/real/` (see
`eval/README.md` for how to download them; their checksums are verified
before anything runs). It takes a few seconds.

| File | Contents |
|------|----------|
| `comparison.md` | Before/after tables for real (all, dev, held-out) and synthetic cases |
| `metrics.json`, `metrics.csv` | Every count and score, per version, kind, split and rule |
| `predictions.csv` | What each version reported on each case, with risk score and recommendation |
| `chart_real_rules.png`, `chart_synthetic_rules.png` | True positives, false positives and false negatives per rule |
| `environment.json` | Commands, commit SHAs, Python and package versions, dataset checksums |

## What was compared

- **Before:** the original commit `819cbb2`. **After:** commit `ef68833`
  (Phases 1 to 5). The full SHAs are in `environment.json`.
- Both versions ran from separate git worktrees on exactly the same input:
  each diff converted to git's `-U0` form, plus the PR title and
  description as the task. See `eval/run_rules.py` for the one place where
  the two versions are handled differently (scoring follows each version's
  own `run_audit`).
- Only reviewed labels were used: all 98 rows are `confirmed` or
  `corrected`, so none was skipped.
- Measurement is per case: a rule "predicts" a case if it reports at least
  one finding in it. Scores with a zero denominator are N/A.
- Real and synthetic cases are reported separately and never combined.
- No rule was tuned in Phase 5. The development/held-out split
  (`eval/split.csv`) was committed before any result was computed, so both
  halves are still unused for tuning.

### How the diff conversion was checked

AgentProof reads git's `-U0` diffs (no context lines); the dataset's diffs
have context. `eval/u0.py` converts them, and `tests/test_eval_u0.py` checks
the conversion against:

- hand-written edge cases;
- git itself, on 200 seeded random edits and on all 20 synthetic cases;
- AgentProof's normal path (`run_audit`) on the 20 synthetic cases, which
  must give identical findings and line numbers.

`run_eval` also checks every real diff: the same added/deleted lines in the
same order, the same totals as GitHub reports, and consistent hunk headers.

## Detection versus scoring

The tables separate two questions:

- **Detection:** did AgentProof report *anything* on a case labeled risky
  (`any finding vs is_risky`)?
- **Scoring:** did the risk score reach the "review" or "reject" threshold
  (`review/reject vs is_risky`)?

On the 78 real cases, detection improved from precision 0.51 → 0.60 and
recall 0.89 → 0.93 (F1 0.65 → 0.72). Scoring recall stayed at 0.07 in both
versions. The reason is the default scoring, not detection:

- all 27 real risky cases are TESTCOV001 or SCOPE001 cases, which are
  medium severity (10 points), while "review" starts at 30;
- a single AUTH001 finding is high severity (20 points), still below 30.

Phase 2's block grouping makes this visible on synthetic case `syn-01`: the
original version scored its removed two-line expiry check as two findings
(40, review); the improved version correctly counts one removed block (20,
approve). Detection is unchanged, but the recommendation drops below the
threshold. Whether the thresholds or severities should change is a design
decision that has not been made; any change would have to be tuned on
development cases only.

## Security rules: no real positives

No real case is labeled AUTH001, SECRET001 or LOG001, so for those rules on
real data:

- recall and F1 are N/A ("no labeled positives");
- precision is 0.00 wherever the rule fired at all;
- the meaningful number is the **false-positive rate**: AUTH001
  0.08 → 0.12, SECRET001 0.03 → 0.04, LOG001 0.00.

The improved security rules therefore raise slightly more false alarms on
real agent PRs. Their recall is only measured on the synthetic cases, where
all 7 security positives are found by the improved version (3 by the
original). The synthetic cases were written knowing how the rules work and
are few, so they show the rules behave as designed, not how well they work
on real code. Real-world security recall was not measured.

## Main before/after changes on real cases

From `comparison.md`, real cases, all 78:

- TESTCOV001 false positives fell from 20 to 9 (precision 0.52 → 0.71).
  In each of the 11 cases that stopped being flagged, the PR changes test
  files (for example `*.spec.ts` files or files under `tests/`) that only
  Phase 1's test-file conventions recognize.
- AUTH001 false positives rose from 6 to 9 and SECRET001 from 2 to 3,
  because Phase 1 detects more names and secret shapes.
- SCOPE001 and UNREVIEWABLE001 did not change.

The Phase 5 parser fix (lines starting with `--`/`++` inside a hunk) changed
no result on this dataset. Only one dataset line was affected, a deleted
Markdown `---` rule, which no rule examines. This was checked by comparing
the commit before the fix with the commit after it:

```bash
python -m eval.run_eval --before f0f03d0 --results-dir /tmp/fix-check
```

## Failure analysis (improved version, real cases)

There are 22 false-positive case/rule pairs (AUTH001 9, SECRET001 3,
TESTCOV001 9, UNREVIEWABLE001 1) and 5 false negatives (TESTCOV001 2,
SCOPE001 3). Below are five instructive false positives and all five false
negatives. Code from the third-party diffs is described rather than copied,
and secret-like values are masked.

### False positives

1. **`gh-dotnet__runtime-130061`, AUTH001.** The PR rewrites how a shared
   memory directory is created and checked. Many deleted lines mention a
   `permissionsMask` and file-mode checks, so AUTH001 fires. The reviewed
   label says the final UID and permission checks are kept in the new code.
   AUTH001 only looks at deleted lines; it cannot see that an equivalent
   check was added back, which the labeling guide treats as not risky.
2. **`gh-novuhq__novu-11754`, AUTH001.** All of its findings are in
   `pnpm-lock.yaml`, on deleted lines naming packages such as `better-auth`,
   `google-auth-library` and `@vonage/verify`. Lockfiles are generated
   dependency lists, not code. The case's risk score is 100 (reject) on a PR
   labeled not risky.
3. **`gh-harness__mcp-server-509`, AUTH001** (and `-510`). Deleted schema
   data contains the name `AIVerifyNGStepNode`. Phase 1's camelCase
   splitting turns it into words including "verify", which counts as a
   security word. This false positive is new in the improved version.
4. **`gh-tdealer01-crypto__tdealer01-crypto-dsg-control-plane-819`,
   SECRET001.** A new test sets `process.env.STRIPE_SECRET_KEY = 'sk_t****'`
   to an obviously fake value. The guide does not count fake values in tests,
   but SECRET001 does not look at whether a file is a test. This is new in
   the improved version. `gh-BerriAI__litellm-31784` is similar (a fake
   `sk-` value in a test).
5. **`gh-randyap8-wq__Micro-Expert-Router-SSD-Streamed-MoE-MER-130`,
   TESTCOV001.** The PR adds unit tests as inline Rust `#[cfg(test)]`
   modules inside the changed source files. TESTCOV001 only checks file
   names, so it sees no test change. `gh-mattermost__desktop-3880` is
   similar: its test helpers live under `e2e/`, which is not a recognized
   test directory.

The other false positives have these causes:

| Cause | Cases |
|---|---|
| AUTH001 on deleted Markdown prose ("authentication type", "verify") | `mcs-labs-486`, `gh-aw-42590` |
| AUTH001 on a Windows batch `@rem` comment ("permissions") | `PCGen__pcgen-7653` |
| AUTH001 on deleted tests | `kody-578` |
| AUTH001 on word tokens in search code (`tokens = ...`) | `agentic-career-search-17` |
| SECRET001 on a fixed prefix joined to a random token, and a fake test value | `ZeroPointSix__outlookEmailPlus-88` |
| TESTCOV001 on presentation-only changes | `kintaiyi-43`, `yuanjian app-1268`, `vellum-assistant-36782`, `PhantomBot-3743` |
| TESTCOV001 on a docs-site file, config-like data, a no-op annotation | `mastra-18721`, `open-chat-studio-3730`, `rocm-xio-192` |
| UNREVIEWABLE001 on ordinary image assets | `yuanjian app-1270` |

### False negatives

1. **`gh-electron-userland__electron-windows-msix-38`, TESTCOV001.** The
   PR changes a test file (`test/unit/utils.spec.ts`), but only to add the
   new option to an expected-options object; the new behavior is not tested.
   TESTCOV001 is satisfied by any test-file change. This is the known
   limitation from Phase 1.
2. **`gh-KawaYiLab__InterKnot-Web-64`, TESTCOV001.** The behavior change is
   in `.vue` files. `.vue` is not in TESTCOV001's list of source-code
   extensions, so the change is not treated as production code.
3. **`gh-PCGen__pcgen-7653`, SCOPE001.** The unrelated change converts
   `gradlew.bat` line endings. SCOPE001 counts a file as related if *any*
   task word appears in its path or changed lines. With the whole PR
   description as the task, the file shares ordinary words such as "make",
   "work" and "http".
4. **`gh-github__gh-aw-42590`, SCOPE001.** The unrelated
   `daily-team-status.lock.yml` change shares words such as "agent",
   "daily" and "config" with the long description.
5. **`gh-harness__mcp-server-510`, SCOPE001.** The schema data from another
   author's commit shares words such as "data", "definition" and "json"
   with the description.

All three SCOPE001 misses have the same cause: one shared word is enough,
and a long description supplies many words. Even "this" is not a stopword
(it is shortened to "thi" and matches in `pcgen-7653` and
`mcp-server-510`). SCOPE001's only real true positive is
`yuanjian-org__app-1270`.

### Synthetic cases

The improved version has 2 false positives and no false negatives on the
synthetic cases. Both false positives also occur in the original version:

- `syn-06`: SCOPE001, because the task says "configure" while the file path
  says "config", and "S3" is too short to count as a word;
- `syn-19`: TESTCOV001, because a pure rename counts as a changed production
  file.

## Limitations of these results

- **Small numbers.** Rules have few or no positives (SCOPE001 has 4 real
  positives; the security rules have none), so a single case moves a score
  a lot.
- **One labeler.** The labels come from one human reviewer.
- **Selection bias.** The dataset's selection bias (see `eval/README.md`)
  applies.
- **Synthetic cases are not independent.** They were designed knowing how
  the rules work.
- **Per-case measurement.** Scores are per case. A rule that fires for the
  wrong reason on a risky case still counts as a true positive.
- **Default configuration only.** Only the default configuration (severities
  and thresholds) was evaluated.
