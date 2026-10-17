"""eval/metrics.py computes the scores correctly on small known fixtures."""

import pytest

from eval.metrics import CaseOutcome, confusion, evaluate, f1_score, ratio, scores


def outcome(case_id, actual=(), predicted=(), recommendation="approve"):
    return CaseOutcome(case_id, frozenset(actual), frozenset(predicted), recommendation)


def test_zero_denominators_are_not_applicable():
    assert ratio(0, 0) is None
    assert f1_score(None, 0.5) is None
    assert f1_score(0.5, None) is None


def test_f1_is_zero_when_precision_and_recall_are_both_zero():
    assert f1_score(0.0, 0.0) == 0.0


def test_f1_is_the_harmonic_mean():
    assert f1_score(0.5, 1.0) == pytest.approx(2 / 3)


def test_confusion_counts_each_combination():
    pairs = [(True, True), (True, False), (False, True), (False, False), (False, False)]
    assert confusion(pairs) == {"tp": 1, "fp": 1, "fn": 1, "tn": 2}


def test_scores_for_a_rule_with_no_labeled_positives():
    # The rule fired once on a negative case: precision 0, recall undefined.
    result = scores({"tp": 0, "fp": 1, "fn": 0, "tn": 3})
    assert result["positives"] == 0
    assert result["precision"] == 0.0
    assert result["recall"] is None
    assert result["f1"] is None
    assert result["false_positive_rate"] == 0.25


def test_scores_for_a_rule_that_never_fired():
    result = scores({"tp": 0, "fp": 0, "fn": 2, "tn": 2})
    assert result["precision"] is None
    assert result["recall"] == 0.0
    assert result["f1"] is None
    assert result["false_positive_rate"] == 0.0


OUTCOMES = [
    # caught, and the score says review
    outcome("a", actual={"AUTH001"}, predicted={"AUTH001", "TESTCOV001"}, recommendation="review"),
    # missed entirely
    outcome("b", actual={"TESTCOV001"}),
    # false alarm on a clean case
    outcome("c", predicted={"SCOPE001"}, recommendation="approve"),
    # clean and quiet
    outcome("d"),
]


def test_evaluate_per_rule():
    per_rule = evaluate(OUTCOMES)["per_rule"]
    assert {k: per_rule["AUTH001"][k] for k in ("tp", "fp", "fn", "tn")} == {"tp": 1, "fp": 0, "fn": 0, "tn": 3}
    assert {k: per_rule["TESTCOV001"][k] for k in ("tp", "fp", "fn", "tn")} == {"tp": 0, "fp": 1, "fn": 1, "tn": 2}
    assert per_rule["TESTCOV001"]["precision"] == 0.0 and per_rule["TESTCOV001"]["recall"] == 0.0
    assert per_rule["TESTCOV001"]["f1"] == 0.0
    assert per_rule["LOG001"]["precision"] is None and per_rule["LOG001"]["recall"] is None


def test_evaluate_rule_groups_and_case_level_scores():
    result = evaluate(OUTCOMES)
    security = result["security_rules"]
    assert (security["tp"], security["fp"], security["fn"], security["tn"]) == (1, 0, 0, 3)
    review = result["review_rules"]
    # a: TESTCOV001 reported, only AUTH001 labeled -> false positive for review rules
    # b: TESTCOV001 labeled, nothing reported      -> false negative
    # c: SCOPE001 reported on a clean case          -> false positive
    # d: nothing either way                         -> true negative
    assert (review["tp"], review["fp"], review["fn"], review["tn"]) == (0, 2, 1, 1)
    any_finding = result["any_finding"]
    assert (any_finding["tp"], any_finding["fp"], any_finding["fn"], any_finding["tn"]) == (1, 1, 1, 1)
    scoring = result["review_or_reject"]
    assert (scoring["tp"], scoring["fp"], scoring["fn"], scoring["tn"]) == (1, 0, 1, 2)
