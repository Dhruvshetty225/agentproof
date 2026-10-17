"""eval/run_llm_eval.py, run with a fake model on the synthetic cases (no Ollama)."""

import json

import pytest

from agentproof.llm_verify import LLMUnavailable
from eval import run_llm_eval
from eval.make_synthetic import CASES, OUT_DIR
from eval.metrics import RULES
from eval.run_eval import Case
from tests.test_llm_verify import FakeClient


def _synthetic_cases(count=4):
    # The reviewed labels of these cases (eval/labels.csv).
    labels = {"syn-01-auth-expiry-removed": {"AUTH001"}, "syn-02-auth-decorator-removed": {"AUTH001"},
              "syn-03-auth-admin-check-removed-js": {"AUTH001"}, "syn-13-testcov-no-tests": {"TESTCOV001"}}
    return [
        Case(case["id"], "synthetic", "dev", frozenset(labels.get(case["id"], ())),
             OUT_DIR / case["id"] / "pr.diff", f"{case['title']}\n\n{case['description']}", None)
        for case in CASES[:count] + [c for c in CASES if c["id"] == "syn-13-testcov-no-tests"]
    ]


class ScriptedClient(FakeClient):
    """Says "no" to every hybrid question; LLM only names AUTH001 on auth diffs."""

    def generate(self, system, prompt, schema):
        self.prompts.append(prompt)
        if "<untrusted_diff>" in prompt:
            if "login_required" in prompt:
                return '{"risky": "yes", "rules": ["AUTH001"], "reason": "A login check was removed."}'
            return '{"risky": "no", "rules": [], "reason": "Nothing risky."}'
        return '{"risky": "no", "reason": "Not risky."}'


def test_llm_only_reply_format_is_strict():
    parse = run_llm_eval.parse_llm_only_reply
    assert parse('{"risky": "yes", "rules": ["AUTH001"], "reason": "x"}') == (frozenset({"AUTH001"}), "x")
    assert parse('{"risky": "no", "rules": [], "reason": "x"}') == (frozenset(), "x")
    assert parse('{"risky": "yes", "rules": [], "reason": "x"}') is None          # yes needs a rule
    assert parse('{"risky": "no", "rules": ["AUTH001"], "reason": "x"}') is None  # no must have none
    assert parse('{"risky": "yes", "rules": ["XSS001"], "reason": "x"}') is None  # unknown rule
    assert parse('{"risky": "yes", "rules": ["AUTH001", "AUTH001"], "reason": "x"}') is None
    assert parse('{"risky": "yes", "rules": ["AUTH001"]}') is None


def test_llm_only_prompt_lists_every_category_and_hides_the_rules_findings():
    prompt = run_llm_eval.build_llm_only_prompt("Fix crash", "diff --git a/x b/x")
    assert all(rule in prompt for rule in RULES)
    assert "Evidence:" not in prompt  # the hybrid excerpt's finding text is not included


def test_three_modes_are_evaluated_on_the_same_cases(tmp_path, monkeypatch):
    monkeypatch.setattr(run_llm_eval, "load_cases", lambda: (_synthetic_cases(), 0))
    results = tmp_path / "llm"
    assert run_llm_eval.main(["--results-dir", str(results)], client=ScriptedClient()) == 0

    metrics = json.loads((results / "metrics.json").read_text(encoding="utf-8"))
    assert set(metrics) == {"rules", "llm_only", "hybrid"}
    synthetic = {mode: metrics[mode]["synthetic"]["all"] for mode in metrics}
    # Rules find all three removed checks; the hybrid model says "no" to everything.
    assert synthetic["rules"]["per_rule"]["AUTH001"]["tp"] == 3
    assert synthetic["hybrid"]["per_rule"]["AUTH001"]["tp"] == 0
    # LLM only names AUTH001 for the login_required diff and nothing else.
    assert synthetic["llm_only"]["per_rule"]["AUTH001"]["tp"] == 1
    assert synthetic["llm_only"]["per_rule"]["AUTH001"]["fn"] == 2
    assert synthetic["llm_only"]["per_rule"]["TESTCOV001"]["fn"] == 1
    assert "review_or_reject" not in synthetic["llm_only"]  # LLM only has no risk score
    assert synthetic["llm_only"]["calls"] == {"answered": 5}

    env = json.loads((results / "environment.json").read_text(encoding="utf-8"))
    assert env["model"] == "fake-model:7b" and env["cost"].startswith("local; no paid API cost")
    assert "Is this change actually risky?" in env["prompts"]["question"]
    comparison = (results / "comparison.md").read_text(encoding="utf-8")
    assert "Rules only P / R / F1" in comparison and "Average seconds per case" in comparison
    decisions = [json.loads(line) for line in (results / "decisions.jsonl").read_text().splitlines()]
    assert {d["mode"] for d in decisions} == {"hybrid", "llm_only"}


def test_benchmark_is_not_run_without_ollama(tmp_path, capsys):
    results = tmp_path / "llm"
    client = FakeClient(version_error=LLMUnavailable("cannot reach Ollama"))
    assert run_llm_eval.main(["--results-dir", str(results)], client=client) == 2
    assert "Benchmark not run" in capsys.readouterr().err
    assert not results.exists()


def test_benchmark_is_not_run_without_the_model(tmp_path, capsys):
    client = FakeClient()
    client.model_info = lambda: {}
    assert run_llm_eval.main(["--results-dir", str(tmp_path / "llm")], client=client) == 2
    assert "is not downloaded" in capsys.readouterr().err
