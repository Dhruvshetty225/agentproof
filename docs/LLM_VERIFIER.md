# Optional local LLM verifier

`agentproof audit --llm-verify` asks a **local** Ollama model whether each
finding is actually risky. It is off by default. Without the flag, AgentProof
behaves and reports exactly as before.

**Benchmark status: not run yet.** No accuracy or speed numbers exist for the
verifier, because Ollama was not installed on the machine used for this
project when the code was written. The commands below produce them once a
model is installed.

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

- A 5-case check finished (`eval/results/llm-smoke/`; 5 development cases,
  so too few for any accuracy claim).
- The full run froze the Mac twice. Swap use reached about 7.6 GB, and the
  Mac had to be force-restarted with the power button during case 13 of 98.
  The Ollama log shows no error before the freeze.
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
