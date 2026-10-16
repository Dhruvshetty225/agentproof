"""eval/summarize_dataset.py computes its numbers correctly from small fixtures."""

from eval.summarize_dataset import collection_summary, label_summary, manifest_summary


def test_manifest_summary_counts_agents_and_repositories():
    rows = [
        {"repository": "a/x", "agent_app": "cursor"},
        {"repository": "a/x", "agent_app": "cursor"},
        {"repository": "b/y", "agent_app": "claude"},
    ]
    assert manifest_summary(rows) == {
        "real_cases": 3,
        "cases_per_agent": {"claude": 1, "cursor": 2},
        "repositories": 2,
        "max_cases_in_one_repository": 2,
    }


def test_collection_summary_totals_exclusions_across_agents():
    report = {
        "settings": {"per_agent": 2},
        "duplicates_skipped": 1,
        "rate_limit_waits": 0,
        "agents": {
            "cursor": {"candidates_seen": 5, "excluded": {"below_min_stars": 3}},
            "claude": {"candidates_seen": 4, "excluded": {"below_min_stars": 1, "fork_repository": 1}},
        },
    }
    summary = collection_summary(report)
    assert summary["candidates_seen"] == 9
    assert summary["exclusions_by_reason"] == {"below_min_stars": 4, "fork_repository": 1}


def test_label_summary_keeps_real_and_synthetic_separate():
    rows = [
        {"case_id": "gh-a-1", "is_risky": "1", "risky_rule_ids": "TESTCOV001;SCOPE001",
         "notes": "UNCERTAIN: x", "review_status": "needs_review"},
        {"case_id": "gh-a-2", "is_risky": "0", "risky_rule_ids": "", "notes": "ok",
         "review_status": "confirmed"},
        {"case_id": "syn-01", "is_risky": "1", "risky_rule_ids": "AUTH001", "notes": "SYNTHETIC",
         "review_status": "needs_review"},
    ]
    summary = label_summary(rows)
    assert summary["real"] == {
        "cases": 2, "is_risky": 1, "per_rule": {"SCOPE001": 1, "TESTCOV001": 1}, "uncertain": 1,
        "review_status": {"needs_review": 1, "confirmed": 1},
    }
    assert summary["synthetic"]["per_rule"] == {"AUTH001": 1}
