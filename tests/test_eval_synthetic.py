"""The synthetic cases are reproducible and clearly marked as synthetic."""

import json
from pathlib import Path

import pytest

from eval.make_synthetic import CASES, OUT_DIR, make_diff


def test_there_are_twenty_uniquely_named_synthetic_cases():
    ids = [case["id"] for case in CASES]
    assert len(ids) == 20
    assert len(set(ids)) == 20
    assert all(case_id.startswith("syn-") for case_id in ids)


def test_diffs_are_deterministic():
    assert make_diff(CASES[0]) == make_diff(CASES[0])


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_committed_files_match_the_generator(case):
    case_dir = OUT_DIR / case["id"]
    with open(case_dir / "pr.diff", encoding="utf-8", newline="") as handle:
        assert handle.read() == make_diff(case)
    metadata = json.loads((case_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["kind"] == "synthetic"
    assert metadata["source_url"] == f"synthetic:{case['id']}"
    assert metadata["title"] == case["title"]


def test_no_synthetic_directory_is_left_over():
    on_disk = sorted(path.name for path in Path(OUT_DIR).iterdir() if path.is_dir())
    assert on_disk == sorted(case["id"] for case in CASES)
