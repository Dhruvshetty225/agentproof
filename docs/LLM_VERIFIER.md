# Optional local LLM verifier

`agentproof audit --llm-verify` asks a **local** Ollama model whether each
finding is actually risky. It is off by default. Without the flag, AgentProof
behaves and reports exactly as before.

**Benchmark status: run once, with the fallback model `qwen2.5-coder:1.5b`.**
See [Measured results](#measured-results-qwen25-coder15b). The preferred
`qwen2.5-coder:7b` was only checked on 5 cases, because its full run froze
the 8 GB Mac used for this project.

## How it works

1. The rules run first, as always.
2. For each finding, AgentProof sends Ollama a bounded excerpt: the finding,
   at most 20 changed lines around it, and the task text (at most 1,000
   characters). Secret values are masked before sending.
3. It asks: *"Is this change actually risky? Answer yes/no with a
   one-sentence reason."* The reply must be exactly
   `{"risky": "yes" | "no", "reason": "<one sentence>"}`.
4. A finding is **suppressed only if all of these hold**:
   - the reply has exactly that format;
   - `risky` is `"no"`;
   - the reason is one line of at most 300 characters;
   - the finding is not critical. Critical findings, which are recognized
     secret formats such as AWS or GitHub keys, are never sent to the model;
   - the code and task contain no text that seems to address an AI model,
     such as "ignore previous instructions". Such findings are not sent.
5. In every other case the finding is **kept**: on "yes", on a malformed
   reply, on a timeout, or when Ollama is not running. After two failures in
   a row AgentProof stops asking and keeps the remaining findings.
6. The risk score is computed from the findings that remain.
7. Every report format lists each decision and the model's reason, and
   lists suppressed findings separately:
   - JSON: `llm_verification` and `llm_suppressed_findings`;
   - SARIF: an "external" suppression;
   - terminal and HTML: a section of their own.

   If Ollama cannot be reached, the report says it is rules-only.

What it cannot do:

- **It cannot add findings.** It can only remove findings the rules made, so
  it cannot find risks the rules missed.
- **Its answer is not a probability.** AgentProof never asks the model for a
  confidence score.
- **The injection check is a heuristic.** The model is told that code is
  data, never instructions. The check for text addressing an AI model is a
  simple heuristic, and a cleverly written comment could still sway the
  model. Suppressed findings stay listed in the report so they can be
  checked.
- **The excerpt is limited.** It shows nearby changed lines, not the whole
  file. A check that was moved far away may not be visible to the model.

## Local only

- The URL must point at this machine (`127.0.0.1`, `::1` or `localhost`),
  and proxy settings are ignored.
- HTTP redirects are refused, so a request cannot be forwarded to another
  host.
- Model names marking Ollama's cloud-hosted models (ending in `cloud`) are
  refused.
- There is no cloud fallback, and no paid API is used.
- The client uses only Python's standard library, so it adds no dependency.

## Setup on macOS

These are the setup steps on a MacBook Air M3 with 8 GB of memory. The
Mac was measured on 2026-10-16:

- 8 GB memory, of which Metal recommends at most 5.73 GB for the GPU;
- 6.8 GiB of free disk, which is too little for a 4.7 GB model.

**Free disk space first.** Leave at least 15 GB free before downloading a
model.

```bash
brew install ollama                      # Ollama 0.20.6, MIT license
ollama serve                             # keep running in its own terminal
curl http://127.0.0.1:11434/api/version  # check it is up
ollama pull qwen2.5-coder:7b             # 4.7 GB download
ollama run qwen2.5-coder:7b --verbose "Answer yes or no with one sentence: is deleting an @login_required decorator risky?"
ollama ps                                # how much runs on the GPU vs the CPU
```

To remove everything:

```bash
ollama rm qwen2.5-coder:7b
brew uninstall ollama
```

### Model choice

| Model | Download | License | Expected fit on 8 GB |
|---|---|---|---|
| `qwen2.5-coder:7b` (default) | 4.7 GB | Apache 2.0 | Very tight: about 1 GB of the GPU limit left for context and buffers, so it may run partly on the CPU and slowly. Must be measured. |
| `llama3.1:8b` | 4.9 GB | Llama 3.1 Community License (free to use, not an open-source license) | Less suitable: larger, and more likely to spill onto the CPU. |
| `qwen2.5-coder:1.5b` | 986 MB | Apache 2.0 | Fits easily, but it is a much weaker model. A fallback, to be reported as such. |

Download sizes and licenses are as listed on ollama.com on 2026-10-16. The
"expected fit" column is a judgment, not a measurement.

**What happened with 7B on this Mac (2026-10-16).**

- A 5-case check finished (5 development cases, so too few for any
  accuracy claim). Its results were kept locally and are not in this
  repository.
- While 7B was loaded, swap use reached about 7.6 GB of 8 GB.
- During the full run the Mac froze at case 13 of 98 and had to be
  force-restarted with the power button. The Ollama log shows no error
  before the freeze. (An earlier restart that evening was deliberate, not a
  freeze.)
- The full benchmark therefore uses `qwen2.5-coder:1.5b` instead, reported
  as a fallback to a weaker model.

## Usage

```bash
agentproof audit --repo . --branch feature --task "..." --llm-verify
agentproof audit --repo . --branch feature --llm-verify --llm-model qwen2.5-coder:1.5b --llm-timeout 180 --format json
```

## Evaluation

```bash
# One real round trip; not a benchmark.
AGENTPROOF_OLLAMA_SMOKE=1 python -m pytest tests/test_llm_smoke.py -s

# A few cases first, to see the speed (results in eval/results/llm-smoke/).
python -m eval.run_llm_eval --limit 5

# All reviewed cases (results in eval/results/llm/).
python -m eval.run_llm_eval
```

`eval/run_llm_eval.py` compares three modes on the same reviewed cases:

- **Rules only:** AgentProof as it is.
- **Hybrid:** the rules plus `--llm-verify`.
- **LLM only:** the model reads the task and the diff, cut to 8,000
  characters, and names which of the six risk categories apply. It never
  sees the rules' findings.

All three modes get the same task text and the same code. It reports
precision, recall and F1 per rule and per case, real and synthetic
separately, plus the average time per case and the outcome of every model
call. It records:

- the model, its digest, the Ollama version and the prompts;
- the settings (temperature 0, seed 0, 4,096-token context) and the
  hardware.

Cost is reported as "local; no paid API cost". Hardware, electricity and
time are still real costs.

If Ollama is not running or the model is not downloaded, the command
prints "Benchmark not run" and writes nothing.

**Saving and resuming:**

- Each finished case is saved at once to `records.jsonl`, so a crash loses
  at most the case in progress.
- Rerunning the same command resumes after the saved cases. It refuses if
  the model, its digest, the Ollama version, the commit or the labels
  changed.
- After 3 cases in a row whose model call failed, the run stops cleanly.
- `--report-only` writes the report from the saved cases without contacting
  Ollama, and marks it PARTIAL with every unprocessed case listed.

**What is scored:**

- All three modes are scored on the same cases: those whose LLM-only call
  returned a valid answer.
- A case whose LLM-only call failed is excluded from every mode and listed
  by name; it is never counted as "nothing risky".
- `coverage.json` and `comparison.md` count how every model call ended:
  - model decisions;
  - findings kept by policy (critical findings);
  - findings kept by the injection check;
  - failures.

The tests (`tests/test_llm_verify.py`, `tests/test_llm_ollama_http.py`,
`tests/test_eval_llm.py`) use a fake model and a fake Ollama server. They
check AgentProof's logic, not the model's quality, and are not benchmarks.

## Measured results (qwen2.5-coder:1.5b)

Every number below comes from the files in `eval/results/llm/`, written by:

```bash
python -m eval.run_llm_eval --model qwen2.5-coder:1.5b
```

The run used the following setup (all recorded in `environment.json`):

- commit `aafd795`, Ollama 0.20.6;
- temperature 0, seed 0, a 4,096-token context and a 120 s timeout;
- one untimed warm-up call of 2.4 s;
- the MacBook Air M3 with 8 GB described above.

It took about 12 minutes for all 98 cases. This is one run of one small
model; it says nothing about larger models.

**Coverage** (`coverage.json`):

- **Processed:** all 98 reviewed cases.
- **Scored:** 96. That is 76 real cases (38 development, 38 held-out) and
  20 synthetic.
- **Excluded:** 2 held-out cases whose LLM-only reply was malformed:
  `gh-electron-forge__electron-forge-docs-261` and `gh-novuhq__novu-11754`.
  They are excluded from all three modes and are not counted as safe.
- **Not run:** none. No call timed out and Ollama was always reachable.

How every model call ended:

| Outcome | Hybrid (one call per finding) | LLM only (one call per case) |
|---|---|---|
| Model decision | 90 (all "risky"; none "not risky") | 96 |
| Kept by policy (critical finding, model not asked) | 2 | - |
| Kept by the injection check (model not asked) | 1 | - |
| Failure: malformed reply (finding kept) | 4 | 2 |

**Scores** (precision / recall / F1, from `comparison.md`):

| Cases | Rules only | LLM only | Hybrid |
|---|---|---|---|
| Real, all 76: any finding vs is_risky | 0.61 / 0.93 / 0.74 | 0.36 / 1.00 / 0.52 | 0.61 / 0.93 / 0.74 |
| Real, all 76: TESTCOV001 | 0.71 / 0.92 / 0.80 | 0.00 / 0.00 / 0.00 | 0.71 / 0.92 / 0.80 |
| Real, development 38: any finding | 0.67 / 1.00 / 0.80 | 0.37 / 1.00 / 0.54 | 0.67 / 1.00 / 0.80 |
| Real, **held-out** 38: any finding | 0.55 / 0.85 / 0.67 | 0.34 / 1.00 / 0.51 | 0.55 / 0.85 / 0.67 |
| Synthetic 20: any finding | 1.00 / 1.00 / 1.00 | 0.55 / 1.00 / 0.71 | 1.00 / 1.00 / 1.00 |
| Synthetic 20: security rules | 1.00 / 1.00 / 1.00 | 0.54 / 1.00 / 0.70 | 1.00 / 1.00 / 1.00 |

Average time per case:

| Cases | Rules only | Hybrid | LLM only |
|---|---|---|---|
| Real, all 76 | 0.00 s | 2.28 s | 4.82 s |
| Synthetic 20 | 0.00 s | 1.22 s | 2.35 s |

The rules-only scores differ slightly from `eval/results/README.md` because
the 2 excluded cases are left out here.

**What this run shows:**

- **The hybrid verifier changed nothing.** All 90 of the model's decisions
  were "risky", so it suppressed no finding, and its scores equal the rules'
  scores. It added about 2 seconds per case.
- **LLM only reported a risk for every scored case.** Its recall of 1.00 is
  therefore not a sign of good detection. Its precision is well below the
  rules': 0.36 vs 0.61 on all real cases, and 0.34 vs 0.55 on held-out
  cases. On real cases it reported AUTH001, SECRET001 and LOG001, which no
  real case is labeled with (precision 0.00 for each). It found none of the
  24 real TESTCOV001 cases.
- **In this run, the local LLM did not improve on the rules.** This is
  measured only for `qwen2.5-coder:1.5b`, a model much weaker than the
  preferred 7B one. Whether a larger model would help was not measured.

To check the claim that LLM only reported something for every scored case,
using `predictions.csv`:

```bash
python -c "import csv; r=[x for x in csv.DictReader(open('eval/results/llm/predictions.csv')) if x['mode']=='llm_only' and x['scored']=='yes']; print(sum(bool(x['reported_rules']) for x in r), 'of', len(r))"
```

Limitations of this run:

- **One run, one small model.** There is one run per case, and model answers
  can change with another Ollama or model version.
- **Truncated diffs.** In LLM only, 22 diffs were longer than the
  8,000-character limit, so the model saw only their start.
- **The verifier's input differs between modes.** The hybrid verifier only
  sees about 20 changed lines around each finding.
- **Raw replies were not saved.** The benchmark saved each model call's parsed status and one-sentence reason, not the model's raw reply. The parsed decisions can be recomputed and checked from `eval/results/llm/`; the exact original replies cannot. For
  example, 4 saved hybrid decisions (all AUTH001 in `novu-11754`) give a
  reason starting "The flagged change is not actually risky" while the
  parsed answer was "risky".
- **The labels' limits apply here too.** The labels have no real security
  positives, and the synthetic cases were written knowing how the rules
  work.
