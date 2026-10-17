"""The development / held-out split is fixed, grouped and balanced."""

import csv
from collections import Counter

from eval.split import DEV, EVAL_DIR, HELDOUT, make_split


def _rows(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


LABELS = [
    {"case_id": "gh-a-1", "is_risky": "1"}, {"case_id": "gh-a-2", "is_risky": "1"},
    {"case_id": "gh-b-1", "is_risky": "1"}, {"case_id": "gh-c-1", "is_risky": "1"},
    {"case_id": "gh-d-1", "is_risky": "0"}, {"case_id": "gh-d-2", "is_risky": "0"},
    {"case_id": "gh-e-1", "is_risky": "0"}, {"case_id": "gh-f-1", "is_risky": "0"},
    {"case_id": "syn-01", "is_risky": "1"},
]
MANIFEST = [{"case_id": row["case_id"], "repository": row["case_id"][3]}
            for row in LABELS if not row["case_id"].startswith("syn-")]


def test_cases_from_one_repository_stay_together():
    split = make_split(LABELS, MANIFEST)
    assert split["gh-a-1"] == split["gh-a-2"]
    assert split["gh-d-1"] == split["gh-d-2"]


def test_synthetic_cases_are_always_development():
    assert make_split(LABELS, MANIFEST)["syn-01"] == (DEV, "synthetic")


def test_the_split_is_deterministic_and_does_not_depend_on_row_order():
    assert make_split(LABELS, MANIFEST) == make_split(list(reversed(LABELS)), list(reversed(MANIFEST)))


def test_repositories_with_the_same_risk_alternate_between_sides():
    split = make_split(LABELS, MANIFEST)
    # b and c each have one risky case: one goes to each side.
    assert {split["gh-b-1"][0], split["gh-c-1"][0]} == {DEV, HELDOUT}
    # e and f each have no risky case: one goes to each side.
    assert {split["gh-e-1"][0], split["gh-f-1"][0]} == {DEV, HELDOUT}


def test_committed_split_matches_the_committed_labels():
    labels = _rows(EVAL_DIR / "labels.csv")
    expected = make_split(labels, _rows(EVAL_DIR / "manifest.csv"))
    committed = {row["case_id"]: (row["split"], row["group"]) for row in _rows(EVAL_DIR / "split.csv")}
    assert committed == expected


def test_committed_split_is_roughly_balanced():
    labels = {row["case_id"]: row["is_risky"] for row in _rows(EVAL_DIR / "labels.csv")}
    real = [row for row in _rows(EVAL_DIR / "split.csv") if row["split"] != DEV or row["group"] != "synthetic"]
    sides = Counter(row["split"] for row in real)
    risky = Counter(row["split"] for row in real if labels[row["case_id"]] == "1")
    assert abs(sides[DEV] - sides[HELDOUT]) <= 4
    assert abs(risky[DEV] - risky[HELDOUT]) <= 2
