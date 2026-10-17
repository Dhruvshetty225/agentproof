"""Make the fixed development / held-out split in eval/split.csv.

    python -m eval.split

Rules:

- Real cases are split about half and half. Both cases from one repository
  always go to the same side, so a repository cannot leak from development
  into held-out.
- Repositories are grouped by how many risky cases they have (0, 1 or 2),
  and each group is dealt out alternately, so both sides get a similar
  share of risky cases.
- Inside a group, repositories are ordered by the SHA-256 of their name.
  There is no randomness: the same labels always give the same split.
- All synthetic cases are development cases. They were written knowing how
  the rules work, so they cannot be a fair held-out test.

The split was made before any evaluation result was computed. Rules may only
be tuned on development cases.
"""

from __future__ import annotations

import csv
import hashlib
import sys
from collections import Counter, defaultdict
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
DEV, HELDOUT = "dev", "heldout"


def _read_csv(path: Path) -> list:
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def make_split(label_rows: list, manifest_rows: list) -> dict:
    """Return {case_id: (split, group)} for every labeled case."""
    repository_of = {row["case_id"]: row["repository"] for row in manifest_rows}
    split = {}
    cases_by_repository = defaultdict(list)
    for row in label_rows:
        if row["case_id"].startswith("syn-"):
            split[row["case_id"]] = (DEV, "synthetic")
        else:
            cases_by_repository[repository_of[row["case_id"]]].append(row)

    def risky_cases(repository: str) -> int:
        return sum(row["is_risky"] == "1" for row in cases_by_repository[repository])

    def name_hash(repository: str) -> str:
        return hashlib.sha256(repository.encode("utf-8")).hexdigest()

    ordered = sorted(cases_by_repository, key=lambda repo: (-risky_cases(repo), name_hash(repo)))
    for position, repository in enumerate(ordered):
        side = DEV if position % 2 == 0 else HELDOUT
        for row in cases_by_repository[repository]:
            split[row["case_id"]] = (side, repository)
    return split


def main(eval_dir: Path = EVAL_DIR) -> int:
    labels = _read_csv(eval_dir / "labels.csv")
    split = make_split(labels, _read_csv(eval_dir / "manifest.csv"))
    with open(eval_dir / "split.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["case_id", "split", "group"])
        for case_id in sorted(split):
            writer.writerow([case_id, *split[case_id]])
    risky = {row["case_id"]: row["is_risky"] == "1" for row in labels}
    counts = Counter((cid.startswith("syn-"), side, risky[cid]) for cid, (side, _) in split.items())
    for (synthetic, side, is_risky), count in sorted(counts.items()):
        kind = "synthetic" if synthetic else "real"
        print(f"{kind:9} {side:7} {'risky' if is_risky else 'not risky':9} {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
