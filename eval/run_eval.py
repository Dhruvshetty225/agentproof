"""Evaluate AgentProof against the reviewed labels, before and after the upgrade.

    python -m eval.run_eval

What it does, in order:

1. Loads every case whose label is reviewed (review_status "confirmed" or
   "corrected"); any other row is counted and skipped. Each case gets its
   split from eval/split.csv.
2. Checks every real diff in eval/data/real/ against the SHA-256 in
   eval/manifest.csv and stops if one is missing or different. (Download
   them with ``python -m eval.collect --from-manifest eval/manifest.csv``.)
3. Converts every diff to git's -U0 form (eval/u0.py) and checks the result:
   the same changed lines in the same order, consistent hunk headers and,
   for real cases, the same totals as GitHub's additions/deletions.
4. Checks out the original commit and the improved commit into temporary git
   worktrees (the current checkout is not touched) and runs
   eval/run_rules.py once for each, with the same Python and packages.
5. Computes the metrics (eval/metrics.py) separately for real and synthetic
   cases, and for real cases also per split, and writes eval/results/.

Collected code is never executed: the diffs are only read as text.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from eval.metrics import RULES, CaseOutcome, evaluate
from eval.u0 import changed_lines, check_u0, to_u0

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parent
ORIGINAL_SHA = "819cbb200640f5753c4c4ca8d5f0bb770ec71889"
REVIEWED = ("confirmed", "corrected")
VERSIONS = ("before", "after")
GROUP_ROWS = (
    ("security_rules", "Security rules (any of AUTH001, SECRET001, LOG001)"),
    ("review_rules", "Review rules (any of TESTCOV001, SCOPE001, UNREVIEWABLE001)"),
    ("any_finding", "Detection: any finding vs is_risky"),
    ("review_or_reject", "Scoring: review/reject vs is_risky"),
)


@dataclass(frozen=True)
class Case:
    case_id: str
    kind: str  # "real" or "synthetic"
    split: str  # "dev" or "heldout"
    actual: frozenset
    diff_path: Path
    task: str
    github_totals: tuple | None  # (additions, deletions) for real cases


def _read_csv(path: Path) -> list:
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_exact(path: Path) -> str:
    """Read text without turning "\\r\\n" into "\\n", as git output is read."""
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def _write_exact(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    result = subprocess.run(["git", "-C", str(REPO_ROOT), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def load_cases(eval_dir: Path = EVAL_DIR) -> tuple[list[Case], int]:
    """Return the reviewed cases and the number of rows skipped as unreviewed."""
    split = {row["case_id"]: row["split"] for row in _read_csv(eval_dir / "split.csv")}
    cases, skipped = [], 0
    for row in _read_csv(eval_dir / "labels.csv"):
        if row["review_status"] not in REVIEWED:
            skipped += 1
            continue
        case_id = row["case_id"]
        actual = frozenset(rule for rule in row["risky_rule_ids"].split(";") if rule)
        if (row["is_risky"] == "1") != bool(actual):
            raise ValueError(f"{case_id}: is_risky does not match risky_rule_ids")
        kind = "synthetic" if case_id.startswith("syn-") else "real"
        case_dir = eval_dir / ("synthetic" if kind == "synthetic" else "data/real") / case_id
        if not (case_dir / "metadata.json").exists():
            raise RuntimeError(f"missing {case_dir}; run: python -m eval.collect --from-manifest eval/manifest.csv")
        metadata = json.loads((case_dir / "metadata.json").read_text(encoding="utf-8"))
        task = f"{metadata['title']}\n\n{metadata.get('description') or ''}"
        totals = (metadata["additions"], metadata["deletions"]) if kind == "real" else None
        cases.append(Case(case_id, kind, split[case_id], actual, case_dir / "pr.diff", task, totals))
    return cases, skipped


def verify_real_diffs(cases: list[Case], manifest_rows: list) -> int:
    """Stop unless every real diff matches the checksum pinned in the manifest."""
    expected = {row["case_id"]: row["diff_sha256"] for row in manifest_rows}
    real = [case for case in cases if case.kind == "real"]
    for case in real:
        if not case.diff_path.exists() or _sha256_file(case.diff_path) != expected[case.case_id]:
            raise RuntimeError(f"{case.diff_path} is missing or does not match eval/manifest.csv")
    return len(real)


def prepare_inputs(cases: list[Case], work_dir: Path) -> Path:
    """Write each case's checked -U0 diff and the adapter's cases.json."""
    entries = []
    for case in cases:
        original = _read_exact(case.diff_path)
        converted = to_u0(original)
        check_u0(converted)
        lines = changed_lines(converted)
        if lines != changed_lines(original):
            raise ValueError(f"{case.case_id}: conversion changed the added/deleted lines")
        if case.github_totals is not None:
            totals = (sum(l.startswith("+") for l in lines), sum(l.startswith("-") for l in lines))
            if totals != tuple(case.github_totals):
                raise ValueError(f"{case.case_id}: {totals} changed lines, GitHub reports {case.github_totals}")
        path = work_dir / f"{case.case_id}.diff"
        _write_exact(path, converted)
        entries.append({"case_id": case.case_id, "diff_path": str(path), "task": case.task})
    cases_json = work_dir / "cases.json"
    cases_json.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return cases_json


@contextmanager
def worktree(sha: str, parent: Path) -> Iterator[Path]:
    """A temporary, detached git worktree of ``sha``; the active checkout is untouched."""
    path = parent / f"worktree-{sha[:12]}"
    _git("worktree", "add", "--detach", "--quiet", str(path), sha)
    try:
        yield path
    finally:
        _git("worktree", "remove", "--force", str(path))


def run_version(root: Path, cases_json: Path, output_json: Path) -> dict:
    """Run the adapter with ``agentproof`` imported from ``root``."""
    env = {**os.environ, "PYTHONPATH": str(root)}
    subprocess.run(
        [sys.executable, str(EVAL_DIR / "run_rules.py"), str(cases_json), str(output_json)],
        check=True, env=env, cwd=output_json.parent,
    )
    result = json.loads(output_json.read_text(encoding="utf-8"))
    if not Path(result["agentproof_file"]).is_relative_to(root.resolve()):
        raise RuntimeError(f"adapter imported {result['agentproof_file']}, not the checkout at {root}")
    return result["cases"]


def outcomes_for(cases: list[Case], version_cases: dict) -> dict:
    return {
        case.case_id: CaseOutcome(
            case_id=case.case_id,
            actual=case.actual,
            predicted=frozenset(version_cases[case.case_id]["findings_per_rule"]),
            recommendation=version_cases[case.case_id]["recommendation"],
        )
        for case in cases
    }


def case_groups(cases: list[Case]) -> dict:
    """{kind: {split: [cases]}}. Synthetic cases are all development cases."""
    real = [case for case in cases if case.kind == "real"]
    synthetic = [case for case in cases if case.kind == "synthetic"]
    return {
        "real": {
            "all": real,
            "dev": [case for case in real if case.split == "dev"],
            "heldout": [case for case in real if case.split == "heldout"],
        },
        "synthetic": {"all": synthetic},
    }


def compute_metrics(cases: list[Case], outcomes: dict) -> dict:
    """{version: {kind: {split: evaluate(...)}}}. Real and synthetic never mix."""
    return {
        version: {
            kind: {
                split: evaluate([outcomes[version][case.case_id] for case in members])
                for split, members in splits.items()
            }
            for kind, splits in case_groups(cases).items()
        }
        for version in VERSIONS
    }


# --- output -------------------------------------------------------------------------


def fmt(value) -> str:
    """Scores for people: 2 decimals, and N/A for an undefined score."""
    if value is None:
        return "N/A"
    return f"{value:.2f}" if isinstance(value, float) else str(value)


def _change(before: dict, after: dict, key: str) -> str:
    old, new = fmt(before[key]), fmt(after[key])
    return new if old == new else f"{old} → {new}"


def comparison_table(before: dict, after: dict) -> list[str]:
    """Markdown rows for one kind and split: per rule, then rule groups."""
    keys = ("tp", "fp", "fn", "tn", "precision", "recall", "f1", "false_positive_rate")
    lines = [
        "| Scope | Positives | TP | FP | FN | TN | Precision | Recall | F1 | FP rate |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    rows = [(rule, rule, before["per_rule"][rule], after["per_rule"][rule]) for rule in RULES]
    rows += [(label, key, before[key], after[key]) for key, label in GROUP_ROWS]
    for label, _, old, new in rows:
        cells = [_change(old, new, key) for key in keys]
        lines.append(f"| {label} | {old['positives']} | " + " | ".join(cells) + " |")
    return lines


def write_comparison(metrics: dict, cases: list[Case], shas: dict, path: Path) -> None:
    groups = case_groups(cases)
    titles = {("real", "all"): "Real cases: all", ("real", "dev"): "Real cases: development split",
              ("real", "heldout"): "Real cases: held-out split",
              ("synthetic", "all"): "Synthetic cases (all development)"}
    lines = [
        "# Before/after comparison",
        "",
        "Generated by `python -m eval.run_eval`. Do not edit by hand.",
        "",
        f"- Before: original commit `{shas['before']}`",
        f"- After: improved commit `{shas['after']}`",
        "- A cell shows `before → after`, or a single value when both are equal.",
        "- Case level: a rule predicts a case when it reports at least one finding in it.",
        "- N/A: the score's denominator is 0 (for example, recall with no labeled positives).",
        "- Real and synthetic cases are never combined.",
        "",
    ]
    for (kind, split), title in titles.items():
        members = groups[kind][split]
        lines += [f"## {title} ({len(members)} cases)", ""]
        lines += comparison_table(metrics["before"][kind][split], metrics["after"][kind][split])
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_predictions(cases: list[Case], raw: dict, path: Path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["version", "case_id", "kind", "split", "labeled_rules", "reported_rules",
                         "findings_per_rule", "ignored_findings", "risk_score", "recommendation"])
        for version in VERSIONS:
            for case in cases:
                result = raw[version][case.case_id]
                per_rule = result["findings_per_rule"]
                writer.writerow([
                    version, case.case_id, case.kind, case.split,
                    ";".join(sorted(case.actual)), ";".join(sorted(per_rule)),
                    ";".join(f"{rule}:{count}" for rule, count in per_rule.items()),
                    result["ignored_findings"], result["risk_score"], result["recommendation"],
                ])


def write_metrics_csv(metrics: dict, path: Path) -> None:
    columns = ("cases", "positives", "tp", "fp", "tn", "fn", "precision", "recall", "f1", "false_positive_rate")
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["version", "kind", "split", "scope", *columns])
        for version, kinds in metrics.items():
            for kind, splits in kinds.items():
                for split, result in splits.items():
                    scopes = [*result["per_rule"].items(), *((key, result[key]) for key, _ in GROUP_ROWS)]
                    for scope, values in scopes:
                        cells = ["" if values[c] is None else
                                 (round(values[c], 4) if isinstance(values[c], float) else values[c])
                                 for c in columns]
                        writer.writerow([version, kind, split, scope, *cells])


def write_charts(metrics: dict, cases: list[Case], results_dir: Path) -> str:
    """Per-rule TP/FP/FN case counts, before vs after; one chart per kind."""
    try:
        import matplotlib
    except ImportError:
        return "skipped: matplotlib is not installed (pip install matplotlib)"
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    groups = case_groups(cases)
    for kind in ("real", "synthetic"):
        figure, axes = plt.subplots(1, 3, figsize=(13, 4.2))
        for axis, key, title in zip(axes, ("tp", "fp", "fn"),
                                    ("True positives", "False positives", "False negatives")):
            positions = range(len(RULES))
            for offset, version, label in ((-0.2, "before", "original"), (0.2, "after", "improved")):
                values = [metrics[version][kind]["all"]["per_rule"][rule][key] for rule in RULES]
                axis.bar([p + offset for p in positions], values, 0.4, label=label)
            axis.set_xticks(list(positions))
            axis.set_xticklabels(RULES, rotation=40, ha="right")
            axis.yaxis.get_major_locator().set_params(integer=True)
            axis.set_title(title)
        axes[0].legend()
        figure.suptitle(f"{kind.capitalize()} cases (n={len(groups[kind]['all'])}): cases per rule")
        figure.tight_layout()
        figure.savefig(results_dir / f"chart_{kind}_rules.png", dpi=120)
        plt.close(figure)
    return "written"


def _package_versions() -> dict:
    versions = {}
    for name in ("typer", "GitPython", "Jinja2", "rich", "matplotlib"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def environment(argv: list, shas: dict, cases: list[Case], skipped: int, real_verified: int) -> dict:
    synthetic_hash = hashlib.sha256()
    for case in sorted((c for c in cases if c.kind == "synthetic"), key=lambda c: c.case_id):
        synthetic_hash.update(case.diff_path.read_bytes())
    return {
        "command": " ".join(["python -m eval.run_eval", *argv]),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "git": subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip(),
        "packages": _package_versions(),
        "commits": shas,
        "agentproof_changes_uncommitted": bool(_git("status", "--porcelain", "--", "agentproof")),
        "dataset": {
            "labels.csv": _sha256_file(EVAL_DIR / "labels.csv"),
            "manifest.csv": _sha256_file(EVAL_DIR / "manifest.csv"),
            "split.csv": _sha256_file(EVAL_DIR / "split.csv"),
            "real_diffs_verified_against_manifest": real_verified,
            "synthetic_diffs_sha256": synthetic_hash.hexdigest(),
        },
        "cases_used": {kind: sum(c.kind == kind for c in cases) for kind in ("real", "synthetic")},
        "rows_skipped_not_reviewed": skipped,
        "u0_conversion": f"checked for all {len(cases)} diffs",
        "code_sha256": {name: _sha256_file(EVAL_DIR / name) for name in ("run_rules.py", "u0.py", "metrics.py")},
    }


def main(argv: list | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--before", default=ORIGINAL_SHA, help="original commit (default: recorded baseline)")
    parser.add_argument("--after", default="HEAD", help="improved commit (default: HEAD)")
    parser.add_argument("--results-dir", type=Path, default=EVAL_DIR / "results")
    args = parser.parse_args(argv)

    try:
        shas = {version: _git("rev-parse", "--verify", f"{ref}^{{commit}}")
                for version, ref in (("before", args.before), ("after", args.after))}
        cases, skipped = load_cases()
        real_verified = verify_real_diffs(cases, _read_csv(EVAL_DIR / "manifest.csv"))
        _git("worktree", "prune")
        raw = {}
        with tempfile.TemporaryDirectory(prefix="agentproof-eval-") as tmp:
            work_dir = Path(tmp)
            cases_json = prepare_inputs(cases, work_dir)
            for version in VERSIONS:
                with worktree(shas[version], work_dir) as root:
                    raw[version] = run_version(root, cases_json, work_dir / f"{version}.json")
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    outcomes = {version: outcomes_for(cases, raw[version]) for version in VERSIONS}
    metrics = compute_metrics(cases, outcomes)
    results_dir = args.results_dir
    results_dir.mkdir(parents=True, exist_ok=True)
    env = environment(argv, shas, cases, skipped, real_verified)
    env["charts"] = write_charts(metrics, cases, results_dir)
    write_predictions(cases, raw, results_dir / "predictions.csv")
    write_metrics_csv(metrics, results_dir / "metrics.csv")
    (results_dir / "metrics.json").write_text(
        json.dumps({"commits": shas, "results": metrics}, indent=2) + "\n", encoding="utf-8")
    write_comparison(metrics, cases, shas, results_dir / "comparison.md")
    (results_dir / "environment.json").write_text(json.dumps(env, indent=2) + "\n", encoding="utf-8")
    print(f"evaluated {len(cases)} reviewed cases ({skipped} unreviewed rows skipped)")
    print(f"results written to {results_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
