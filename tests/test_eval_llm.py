"""eval/run_llm_eval.py, run with a fake model on the synthetic cases (no Ollama)."""

import json

import pytest

from agentproof.llm_verify import LLMTimeout, LLMUnavailable
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
    assert env["warmup_seconds"] >= 0
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


def test_benchmark_is_not_run_when_the_warm_up_fails(tmp_path, capsys, five_cases):
    client = FakeClient([LLMUnavailable("model failed to load")])
    assert run_llm_eval.main(["--results-dir", str(tmp_path / "llm")], client=client) == 2
    assert "warm-up call failed" in capsys.readouterr().err
    assert client.timeout == 5.0  # the longer warm-up timeout is undone


def test_benchmark_is_not_run_without_the_model(tmp_path, capsys):
    client = FakeClient()
    client.model_info = lambda: {}
    assert run_llm_eval.main(["--results-dir", str(tmp_path / "llm")], client=client) == 2
    assert "is not downloaded" in capsys.readouterr().err


# --- saving, resuming and honest coverage ------------------------------------------------


def _llm_only_calls(client):
    return sum("<untrusted_diff>" in prompt for prompt in client.prompts)


@pytest.fixture
def five_cases(monkeypatch):
    monkeypatch.setattr(run_llm_eval, "load_cases", lambda: (_synthetic_cases(), 0))


def test_each_case_is_saved_and_a_rerun_resumes(tmp_path, five_cases):
    results = tmp_path / "llm"
    first = ScriptedClient()
    assert run_llm_eval.main(["--results-dir", str(results), "--limit", "3"], client=first) == 0
    assert len((results / "records.jsonl").read_text().splitlines()) == 3
    second = ScriptedClient()
    assert run_llm_eval.main(["--results-dir", str(results)], client=second) == 0
    assert _llm_only_calls(second) == 2  # only the two cases not saved yet
    assert len((results / "records.jsonl").read_text().splitlines()) == 5
    cover = json.loads((results / "coverage.json").read_text())
    assert (cover["processed"], cover["scored"], cover["not_processed"]) == (5, 5, [])
    assert len(json.loads((results / "environment.json").read_text())["warmups"]) == 2


def test_saved_cases_from_other_settings_are_never_mixed_in(tmp_path, five_cases):
    results = tmp_path / "llm"
    assert run_llm_eval.main(["--results-dir", str(results), "--limit", "2"], client=ScriptedClient()) == 0
    saved = (results / "records.jsonl").read_text()
    other_model = ScriptedClient()
    other_model.model = "other-model:1b"
    assert run_llm_eval.main(["--results-dir", str(results)], client=other_model) == 2
    assert other_model.prompts == []
    assert (results / "records.jsonl").read_text() == saved


def test_an_incomplete_last_line_is_ignored_and_that_case_runs_again(tmp_path, five_cases):
    results = tmp_path / "llm"
    assert run_llm_eval.main(["--results-dir", str(results), "--limit", "2"], client=ScriptedClient()) == 0
    with open(results / "records.jsonl", "a", encoding="utf-8") as handle:
        handle.write('{"case_id": "syn-03-auth-admin-check-re')  # cut off by a crash
    client = ScriptedClient()
    assert run_llm_eval.main(["--results-dir", str(results)], client=client) == 0
    assert _llm_only_calls(client) == 3


class TimeoutOnLogin(ScriptedClient):
    """The LLM-only call times out on the login_required case."""

    def generate(self, system, prompt, schema):
        if "<untrusted_diff>" in prompt and "login_required" in prompt:
            self.prompts.append(prompt)
            raise LLMTimeout("no answer within 5 s")
        return super().generate(system, prompt, schema)


def test_a_failed_llm_only_call_is_excluded_from_every_mode_and_listed(tmp_path, five_cases):
    results = tmp_path / "llm"
    assert run_llm_eval.main(["--results-dir", str(results)], client=TimeoutOnLogin()) == 0
    cover = json.loads((results / "coverage.json").read_text())
    assert cover["excluded_llm_only_failed"] == {"syn-02-auth-decorator-removed": "timeout"}
    assert (cover["processed"], cover["scored"]) == (5, 4)
    metrics = json.loads((results / "metrics.json").read_text())
    for mode in ("rules", "llm_only", "hybrid"):
        assert metrics[mode]["synthetic"]["all"]["any_finding"]["cases"] == 4
    # The rules still found the other two removed checks; the failed case is not counted either way.
    assert metrics["rules"]["synthetic"]["all"]["per_rule"]["AUTH001"]["tp"] == 2
    comparison = (results / "comparison.md").read_text()
    assert "syn-02-auth-decorator-removed (timeout)" in comparison
    assert "failure: timeout" in comparison


class AlwaysTimesOut(ScriptedClient):
    def generate(self, system, prompt, schema):
        if "<untrusted_diff>" in prompt:
            self.prompts.append(prompt)
            raise LLMTimeout("no answer within 5 s")
        return super().generate(system, prompt, schema)


def test_repeated_failures_stop_the_run_and_keep_finished_cases(tmp_path, five_cases):
    results = tmp_path / "llm"
    assert run_llm_eval.main(["--results-dir", str(results)], client=AlwaysTimesOut()) == 3
    assert len((results / "records.jsonl").read_text().splitlines()) == 3
    cover = json.loads((results / "coverage.json").read_text())
    assert len(cover["not_processed"]) == 2 and cover["scored"] == 0
    assert "PARTIAL RUN: 2 case(s) not processed" in (results / "comparison.md").read_text()


def test_report_only_needs_no_model_and_marks_a_partial_run(tmp_path, five_cases):
    results = tmp_path / "llm"
    assert run_llm_eval.main(["--results-dir", str(results), "--limit", "2"], client=ScriptedClient()) == 0

    class NoCalls(ScriptedClient):
        def version(self):
            raise AssertionError("report-only must not contact the model")

    assert run_llm_eval.main(["--results-dir", str(results), "--report-only"], client=NoCalls()) == 0
    comparison = (results / "comparison.md").read_text()
    assert "PARTIAL RUN: 3 case(s) not processed" in comparison
    assert "not counted as safe" in comparison


def test_report_only_without_a_saved_run_says_so(tmp_path, five_cases, capsys):
    assert run_llm_eval.main(["--results-dir", str(tmp_path / "none"), "--report-only"]) == 2
    assert "Nothing to report" in capsys.readouterr().err


def _dataset_missing():
    raise RuntimeError("missing eval/data/real/gh-x; run: python -m eval.collect --from-manifest eval/manifest.csv")


def test_a_missing_dataset_stops_cleanly_after_the_ollama_checks(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run_llm_eval, "load_cases", _dataset_missing)
    results = tmp_path / "llm"
    client = ScriptedClient()
    assert run_llm_eval.main(["--results-dir", str(results)], client=client) == 2
    error = capsys.readouterr().err
    assert "Benchmark not run" in error and "eval.collect --from-manifest" in error
    assert client.prompts == []  # no warm-up and no model call without data
    assert not results.exists()


def test_ollama_is_checked_before_the_dataset(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run_llm_eval, "load_cases", _dataset_missing)
    client = FakeClient(version_error=LLMUnavailable("cannot reach Ollama"))
    assert run_llm_eval.main(["--results-dir", str(tmp_path / "llm")], client=client) == 2
    assert "Start Ollama" in capsys.readouterr().err


def test_report_only_with_a_missing_dataset_says_so(tmp_path, five_cases, monkeypatch, capsys):
    results = tmp_path / "llm"
    assert run_llm_eval.main(["--results-dir", str(results), "--limit", "2"], client=ScriptedClient()) == 0
    monkeypatch.setattr(run_llm_eval, "load_cases", _dataset_missing)
    assert run_llm_eval.main(["--results-dir", str(results), "--report-only"]) == 2
    assert "Report not written" in capsys.readouterr().err
