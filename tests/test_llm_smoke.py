"""Optional smoke test against a REAL local Ollama. Skipped unless asked for.

    AGENTPROOF_OLLAMA_SMOKE=1 python -m pytest tests/test_llm_smoke.py -s

It needs Ollama running locally with the model downloaded (see
docs/LLM_VERIFIER.md). Set AGENTPROOF_OLLAMA_MODEL to try another model.
It checks that one real round trip works and prints how long it took. It
is not a benchmark: one answer says nothing about accuracy.
"""

import os
import time

import pytest

from agentproof.diff_parser import ChangedLine, FileDiff
from agentproof.llm_verify import DEFAULT_MODEL, LLMError, LLMVerifier, OllamaClient
from agentproof.schema import DiffSide, Finding, Severity

pytestmark = pytest.mark.skipif(
    os.environ.get("AGENTPROOF_OLLAMA_SMOKE") != "1",
    reason="real Ollama smoke test; set AGENTPROOF_OLLAMA_SMOKE=1 to run it",
)


def test_one_real_round_trip():
    client = OllamaClient(model=os.environ.get("AGENTPROOF_OLLAMA_MODEL", DEFAULT_MODEL))
    try:
        version = client.version()
    except LLMError as error:
        pytest.fail(f"Ollama is not reachable: {error}")
    if not client.model_info():
        pytest.fail(f"model {client.model} is not downloaded (ollama pull {client.model})")

    finding = Finding("AUTH001", Severity.HIGH, "Security check removed", "app/views.py", 3,
                      "@login_required", "Review it.", side=DiffSide.OLD)
    diffs = [FileDiff("app/views.py", deleted_lines=[ChangedLine(3, "@login_required")])]
    started = time.monotonic()
    kept, suppressed, summary = LLMVerifier(client).verify([finding], diffs, "Fix the settings page")
    seconds = time.monotonic() - started

    decision = summary.decisions[0]
    print(f"\nOllama {version}, {client.model}: {decision.status} in {seconds:.1f} s: {decision.reason}")
    assert decision.status in ("confirmed_risky", "judged_not_risky", "malformed_reply", "timeout")
    assert len(kept) + len(suppressed) == 1
