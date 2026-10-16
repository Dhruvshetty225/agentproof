"""Print the dataset numbers quoted in eval/README.md, from committed files only.

    python -m eval.summarize_dataset

Reads eval/manifest.csv, eval/collection_report.json and eval/labels.csv.
Label counts are TENTATIVE until each row's review_status is confirmed or
corrected; they are not ground truth and are not evaluation results.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent


def _read_csv(path: Path) -> list:
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def manifest_summary(rows: list) -> dict:
    per_repo = Counter(row["repository"] for row in rows)
    return {
        "real_cases": len(rows),
        "cases_per_agent": dict(sorted(Counter(row["agent_app"] for row in rows).items())),
        "repositories": len(per_repo),
        "max_cases_in_one_repository": max(per_repo.values(), default=0),
    }


def collection_summary(report: dict) -> dict:
    agents = report["agents"]
    exclusions = Counter()
    for stats in agents.values():
        exclusions.update(stats["excluded"])
    return {
        "settings": report["settings"],
        "candidates_seen": sum(s["candidates_seen"] for s in agents.values()),
        "candidates_seen_per_agent": {slug: s["candidates_seen"] for slug, s in agents.items()},
        "exclusions_by_reason": dict(exclusions.most_common()),
        "duplicates_skipped": report["duplicates_skipped"],
        "rate_limit_waits": report["rate_limit_waits"],
    }


def label_summary(rows: list) -> dict:
    summary = {}
    for kind, is_kind in (("real", lambda r: not r["case_id"].startswith("syn-")),
                          ("synthetic", lambda r: r["case_id"].startswith("syn-"))):
        selected = [r for r in rows if is_kind(r)]
        per_rule = Counter(rule for r in selected for rule in r["risky_rule_ids"].split(";") if rule)
        summary[kind] = {
            "cases": len(selected),
            "is_risky": sum(r["is_risky"] == "1" for r in selected),
            "per_rule": dict(sorted(per_rule.items())),
            "uncertain": sum("UNCERTAIN" in r["notes"] for r in selected),
            "review_status": dict(Counter(r["review_status"] for r in selected)),
        }
    return summary


def main(eval_dir: Path = EVAL_DIR) -> int:
    report = json.loads((eval_dir / "collection_report.json").read_text(encoding="utf-8"))
    output = {
        "manifest": manifest_summary(_read_csv(eval_dir / "manifest.csv")),
        "collection": collection_summary(report),
        "tentative_labels": label_summary(_read_csv(eval_dir / "labels.csv")),
    }
    json.dump(output, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
