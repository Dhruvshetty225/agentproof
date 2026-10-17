"""Evaluation adapter: run one AgentProof version on prepared -U0 diffs.

    PYTHONPATH=<agentproof checkout> python eval/run_rules.py CASES_JSON OUTPUT_JSON

eval/run_eval.py runs this once for the original version and once for the
improved version, each from its own git worktree on PYTHONPATH. Run it as a
script (not with ``-m``), so ``agentproof`` is imported from that checkout.

CASES_JSON is a list of {"case_id", "diff_path", "task"}. Every version gets
exactly the same diff text and task, and goes through the same steps:

1. parse the diff with the version's own parser (``_parse_unified_diff``);
2. run every rule in the version's ``ALL_RULES``;
3. post-process and score the findings the way that version's run_audit does.

Step 3 is the only compatibility handling. run_audit itself changed in the
upgrade: the original version deduplicates and then scores, while the
improved version's ``engine.collect_findings`` also applies ignore
directives, groups deleted blocks and applies configured severities (none,
with the default configuration used here). The adapter calls whichever the
version has, so each version is scored the way its own CLI would score it.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


def audit(diff_text: str, task: str) -> dict:
    """Run the importable AgentProof version on one diff."""
    from agentproof import engine
    from agentproof.diff_parser import _parse_unified_diff
    from agentproof.rules import ALL_RULES

    file_diffs = _parse_unified_diff(diff_text)
    if hasattr(engine, "collect_findings"):  # improved version
        findings, ignored = engine.collect_findings(file_diffs, task=task)
    else:  # original version: the same steps as its run_audit
        findings = []
        for rule_module in ALL_RULES:
            findings.extend(rule_module.check(file_diffs, task=task))
        findings, ignored = engine._deduplicate(findings), []
    risk_score = engine.calculate_risk_score(findings)
    return {
        "findings_per_rule": dict(sorted(Counter(f.rule_id for f in findings).items())),
        "ignored_findings": len(ignored),
        "risk_score": risk_score,
        "recommendation": engine.recommend(risk_score).value,
    }


def main(cases_json: str, output_json: str) -> int:
    import agentproof

    cases = json.loads(Path(cases_json).read_text(encoding="utf-8"))
    results = {}
    for case in cases:
        # newline="" keeps "\r\n" as it is, the way git's output reaches AgentProof.
        with open(case["diff_path"], encoding="utf-8", newline="") as handle:
            results[case["case_id"]] = audit(handle.read(), case["task"])
    output = {"agentproof_file": str(Path(agentproof.__file__).resolve()), "cases": results}
    Path(output_json).write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    # Python puts this script's folder (eval/) first on sys.path. Remove it so
    # nothing in eval/ can shadow a module that agentproof imports.
    here = Path(__file__).resolve().parent
    sys.path[:] = [entry for entry in sys.path if Path(entry or ".").resolve() != here]
    sys.exit(main(sys.argv[1], sys.argv[2]))
