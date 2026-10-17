"""The evaluation runner and its per-version adapter behave as documented."""

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agentproof import engine
from agentproof.diff_parser import _parse_unified_diff
from agentproof.rules import ALL_RULES
from eval import run_rules
from eval.make_synthetic import CASES, OUT_DIR
from eval.run_eval import EVAL_DIR, REPO_ROOT, fmt, load_cases, prepare_inputs
from eval.u0 import to_u0

REAL_ID = "gh-owner__repo-1"


def _synthetic_task(case):
    return f"{case['title']}\n\n{case['description']}"


def test_adapter_runs_the_checkout_on_pythonpath(tmp_path):
    case = CASES[0]
    diff_path = tmp_path / "case.diff"
    diff_path.write_text(to_u0((OUT_DIR / case["id"] / "pr.diff").read_text(encoding="utf-8")), encoding="utf-8")
    cases_json = tmp_path / "cases.json"
    cases_json.write_text(json.dumps([{"case_id": case["id"], "diff_path": str(diff_path),
                                       "task": _synthetic_task(case)}]), encoding="utf-8")
    output = tmp_path / "out.json"
    subprocess.run([sys.executable, str(EVAL_DIR / "run_rules.py"), str(cases_json), str(output)],
                   check=True, env={**os.environ, "PYTHONPATH": str(REPO_ROOT)}, cwd=tmp_path)
    result = json.loads(output.read_text(encoding="utf-8"))
    assert Path(result["agentproof_file"]).is_relative_to(REPO_ROOT)
    assert result["cases"][case["id"]]["findings_per_rule"] == {"AUTH001": 1}


def test_adapter_uses_the_original_steps_when_collect_findings_is_missing(monkeypatch):
    case = next(c for c in CASES if c["id"] == "syn-06-secret-aws-key-id")
    diff_text = to_u0((OUT_DIR / case["id"] / "pr.diff").read_text(encoding="utf-8"))
    task = _synthetic_task(case)
    expected = []
    for rule_module in ALL_RULES:
        expected.extend(rule_module.check(_parse_unified_diff(diff_text), task=task))
    expected = engine._deduplicate(expected)

    monkeypatch.delattr(engine, "collect_findings")
    result = run_rules.audit(diff_text, task)
    assert result["findings_per_rule"] == {"SCOPE001": 1, "SECRET001": 1}
    assert sum(result["findings_per_rule"].values()) == len(expected)
    assert result["risk_score"] == engine.calculate_risk_score(expected)
    assert result["ignored_findings"] == 0


def _write_dataset(eval_dir, labels):
    (eval_dir / "data" / "real" / REAL_ID).mkdir(parents=True)
    (eval_dir / "synthetic" / "syn-01").mkdir(parents=True)
    (eval_dir / "data" / "real" / REAL_ID / "metadata.json").write_text(json.dumps(
        {"title": "Fix bug", "description": None, "additions": 1, "deletions": 1}), encoding="utf-8")
    (eval_dir / "synthetic" / "syn-01" / "metadata.json").write_text(json.dumps(
        {"title": "Synthetic", "description": "Example."}), encoding="utf-8")
    with open(eval_dir / "labels.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(labels[0]))
        writer.writeheader()
        writer.writerows(labels)
    with open(eval_dir / "split.csv", "w", encoding="utf-8", newline="") as handle:
        handle.write(f"case_id,split,group\n{REAL_ID},heldout,owner/repo\nsyn-01,dev,synthetic\n")


def _label(case_id, rules="", status="confirmed"):
    return {"case_id": case_id, "source_url": "", "is_risky": "1" if rules else "0",
            "risky_rule_ids": rules, "notes": "", "review_status": status}


def test_load_cases_uses_only_reviewed_labels(tmp_path):
    _write_dataset(tmp_path, [_label(REAL_ID, "TESTCOV001", "corrected"), _label("syn-01", status="needs_review")])
    cases, skipped = load_cases(tmp_path)
    assert [case.case_id for case in cases] == [REAL_ID]
    assert skipped == 1
    assert cases[0].actual == frozenset({"TESTCOV001"})
    assert cases[0].split == "heldout"
    assert cases[0].task == "Fix bug\n\n"
    assert cases[0].github_totals == (1, 1)


def test_load_cases_rejects_inconsistent_labels(tmp_path):
    bad = _label(REAL_ID, "TESTCOV001")
    bad["is_risky"] = "0"
    _write_dataset(tmp_path, [bad, _label("syn-01")])
    with pytest.raises(ValueError):
        load_cases(tmp_path)


def test_prepare_inputs_rejects_a_diff_that_disagrees_with_github_totals(tmp_path):
    _write_dataset(tmp_path, [_label(REAL_ID), _label("syn-01")])
    diff = ("diff --git a/f.py b/f.py\nindex 1..2 100644\n--- a/f.py\n+++ b/f.py\n"
            "@@ -1,2 +1,3 @@\n a\n-b\n+B\n+C\n")
    (tmp_path / "data" / "real" / REAL_ID / "pr.diff").write_text(diff, encoding="utf-8")
    (tmp_path / "synthetic" / "syn-01" / "pr.diff").write_text(diff, encoding="utf-8")
    cases, _ = load_cases(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(ValueError, match="GitHub reports"):
        prepare_inputs(cases, work)  # 2 additions in the diff, metadata says 1


def test_prepare_inputs_writes_converted_diffs(tmp_path):
    _write_dataset(tmp_path, [_label(REAL_ID), _label("syn-01")])
    diff = ("diff --git a/f.py b/f.py\nindex 1..2 100644\n--- a/f.py\n+++ b/f.py\n"
            "@@ -1,3 +1,3 @@\n a\n-b\r\n+B\r\n c\n")
    for folder in (tmp_path / "data" / "real" / REAL_ID, tmp_path / "synthetic" / "syn-01"):
        (folder / "pr.diff").write_bytes(diff.encode("utf-8"))
    cases, _ = load_cases(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    entries = json.loads(prepare_inputs(cases, work).read_text(encoding="utf-8"))
    converted = Path(entries[0]["diff_path"]).read_bytes().decode("utf-8")
    assert converted.endswith("@@ -2 +2 @@\n-b\r\n+B\r\n")  # CRLF content kept as is


def test_fmt_shows_undefined_scores_as_not_applicable():
    assert fmt(None) == "N/A"
    assert fmt(0.5) == "0.50"
    assert fmt(3) == "3"
