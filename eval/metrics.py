"""Precision, recall and F1 for AgentProof's predictions against reviewed labels.

Everything is measured per case, not per finding: a rule "predicts" a case
when it reports at least one finding in it, and the case is "actually"
positive for that rule when the rule is in the case's ``risky_rule_ids``.

Zero denominators: a score whose denominator is 0 is ``None`` (shown as
N/A), never 0 or 1. Precision is N/A when the rule never fired, recall is
N/A when there are no labeled positives, and F1 is N/A when either of them
is. When both are defined and both are 0, F1 is 0.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

RULES = ("AUTH001", "SECRET001", "LOG001", "TESTCOV001", "SCOPE001", "UNREVIEWABLE001")
SECURITY_RULES = frozenset({"AUTH001", "SECRET001", "LOG001"})
REVIEW_RULES = frozenset({"TESTCOV001", "SCOPE001", "UNREVIEWABLE001"})


@dataclass(frozen=True)
class CaseOutcome:
    """What the labels say about one case, and what AgentProof reported."""

    case_id: str
    actual: frozenset  # rule IDs in the case's label
    predicted: frozenset  # rule IDs AgentProof reported at least once
    recommendation: str  # "approve", "review" or "reject"


def ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def f1_score(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def confusion(pairs: Iterable[tuple[bool, bool]]) -> dict:
    """Count (predicted, actual) pairs into TP, FP, TN and FN."""
    counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    for predicted, actual in pairs:
        if predicted and actual:
            counts["tp"] += 1
        elif predicted:
            counts["fp"] += 1
        elif actual:
            counts["fn"] += 1
        else:
            counts["tn"] += 1
    return counts


def scores(counts: dict) -> dict:
    """Add the derived scores to a confusion count."""
    precision = ratio(counts["tp"], counts["tp"] + counts["fp"])
    recall = ratio(counts["tp"], counts["tp"] + counts["fn"])
    return {
        **counts,
        "cases": sum(counts.values()),
        "positives": counts["tp"] + counts["fn"],
        "precision": precision,
        "recall": recall,
        "f1": f1_score(precision, recall),
        # How often the rule fires on a case labeled negative for it.
        "false_positive_rate": ratio(counts["fp"], counts["fp"] + counts["tn"]),
    }


def evaluate(outcomes: list[CaseOutcome]) -> dict:
    """All scores for one group of cases (for example: real, held-out)."""

    def any_of(rules: frozenset, found: frozenset) -> bool:
        return bool(rules & found)

    return {
        "per_rule": {
            rule: scores(confusion((rule in o.predicted, rule in o.actual) for o in outcomes))
            for rule in RULES
        },
        # A case is positive for a group when any rule of the group applies.
        "security_rules": scores(confusion(
            (any_of(SECURITY_RULES, o.predicted), any_of(SECURITY_RULES, o.actual)) for o in outcomes)),
        "review_rules": scores(confusion(
            (any_of(REVIEW_RULES, o.predicted), any_of(REVIEW_RULES, o.actual)) for o in outcomes)),
        # Detection: did AgentProof report anything on a risky case?
        "any_finding": scores(confusion((bool(o.predicted), bool(o.actual)) for o in outcomes)),
        # Scoring: did the risk score reach "review" or "reject" on a risky case?
        "review_or_reject": scores(confusion(
            (o.recommendation in ("review", "reject"), bool(o.actual)) for o in outcomes)),
    }
