"""Collect real pull requests authored by AI coding agents on public GitHub.

Usage (the token is read from the GITHUB_TOKEN environment variable and is
never printed or saved):

    python -m eval.collect                                    # search and collect
    python -m eval.collect --from-manifest eval/manifest.csv  # re-fetch pinned cases

Selection, per agent in eval/agents.py:

1. Search ``is:pr is:public is:merged author:app/<slug> created:<since>..<until>``
   sorted by creation date (oldest first), up to 10 pages.
2. Keep a PR only if its author is that app's bot account (type "Bot", known
   login and ID). This is the AI-involvement evidence saved with the case.
3. Skip forks, archived repositories and repositories with fewer than
   ``min_stars`` stars; skip PRs over the size limits; take at most
   ``max_per_repo`` PRs from one repository and ``per_agent`` per agent.
4. Download the diff between the PR's pinned base and head commits
   (``/compare/<base>...<head>``), and reject it if it is too large or if its
   +/- line counts differ from the PR's additions/deletions (truncated or
   changed diff).

Each case is saved as ``<out>/<case_id>/metadata.json`` and ``pr.diff``;
metadata.json is written last, so its presence marks a complete case and an
interrupted run can be resumed. Excluded PRs are logged in
``<out>/exclusions.jsonl`` with a reason and are not fetched again, except for
API errors and the per-repository cap, which are retried on the next run.

Safety: nothing collected is executed. Titles, descriptions and diffs are
untrusted text; they are only stored as data and are never printed while
collecting.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from eval.agents import AGENT_APPS, AgentApp
from eval.github_api import ApiError, GitHubClient

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_OUT_DIR = EVAL_DIR / "data" / "real"
DEFAULT_MANIFEST = EVAL_DIR / "manifest.csv"
DEFAULT_REPORT = EVAL_DIR / "collection_report.json"
MANIFEST_COLUMNS = [
    "case_id", "source_url", "repository", "pr_number", "agent_app", "title",
    "base_sha", "head_sha", "diff_sha256", "collected_at",
]
# Exclusions that depend on the current run's state, not on the PR itself.
# They are counted in the report but not logged, so a later run retries them.
_TRANSIENT_REASONS = {"repository_cap_reached"}


def _is_transient(reason: str) -> bool:
    # API errors may be temporary (a 502 after all retries, a network outage).
    return reason in _TRANSIENT_REASONS or reason.startswith("api_error_")


@dataclass(frozen=True)
class Settings:
    since: str = "2026-07-01"
    until: str = "2026-09-30"
    per_agent: int = 12
    max_per_repo: int = 2
    min_stars: int = 10
    max_changed_files: int = 50
    max_changed_lines: int = 1500
    max_diff_bytes: int = 1_000_000
    max_search_pages: int = 10


# --- pure selection rules (unit tested) ----------------------------------------


def search_query(agent: AgentApp, settings: Settings) -> str:
    return (
        f"is:pr is:public is:merged author:app/{agent.slug} "
        f"created:{settings.since}..{settings.until}"
    )


def case_id_for(repository: str, number: int) -> str:
    """Stable, readable ID: "gh-<owner>__<repo>-<number>"."""
    owner, name = repository.split("/", 1)
    return "gh-" + re.sub(r"[^A-Za-z0-9._-]+", "-", f"{owner}__{name}") + f"-{number}"


def bot_evidence(user: dict, agent: AgentApp) -> Optional[dict]:
    """The AI-involvement evidence for a PR author, or None if not the agent's bot."""
    if (
        user.get("type") != "Bot"
        or user.get("login") != agent.bot_login
        or user.get("id") != agent.bot_id
    ):
        return None
    return {
        "type": "verified_bot_author",
        "agent": agent.agent,
        "app_slug": agent.slug,
        "app_owner": agent.owner,
        "app_url": agent.app_url,
        "author_login": user["login"],
        "author_id": user["id"],
        "author_type": user["type"],
    }


def repository_exclusion(repo_info: dict, settings: Settings) -> Optional[str]:
    if repo_info.get("private"):
        return "private_repository"
    if repo_info.get("fork"):
        return "fork_repository"
    if repo_info.get("archived"):
        return "archived_repository"
    if repo_info.get("stargazers_count", 0) < settings.min_stars:
        return "below_min_stars"
    return None


def pull_request_exclusion(pr: dict, settings: Settings) -> Optional[str]:
    if not pr.get("merged_at"):
        return "not_merged"
    changed_lines = pr["additions"] + pr["deletions"]
    if changed_lines == 0:
        return "no_line_changes"
    if pr["changed_files"] > settings.max_changed_files:
        return "too_many_files"
    if changed_lines > settings.max_changed_lines:
        return "too_many_changed_lines"
    return None


def count_diff_lines(diff_text: str) -> tuple[int, int]:
    """(added, deleted) lines, counting only lines inside hunks.

    File headers ("--- a/x", "+++ b/x") come before a file's first "@@" line,
    so a deleted line whose text starts with "--" is still counted correctly.
    """
    additions = deletions = 0
    in_hunk = False
    # split("\n") rather than splitlines(): code can contain form feeds and
    # other characters that splitlines() would treat as line breaks.
    for line in diff_text.split("\n"):
        if line.startswith("diff --git "):
            in_hunk = False
        elif line.startswith("@@"):
            in_hunk = True
        elif in_hunk and line.startswith("+"):
            additions += 1
        elif in_hunk and line.startswith("-"):
            deletions += 1
    return additions, deletions


def diff_exclusion(diff_text: str, pr: dict, settings: Settings) -> Optional[str]:
    if len(diff_text.encode("utf-8")) > settings.max_diff_bytes:
        return "diff_too_large"
    if not diff_text.strip():
        return "empty_diff"
    if count_diff_lines(diff_text) != (pr["additions"], pr["deletions"]):
        return "diff_line_count_mismatch"
    return None


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_metadata(
    pr: dict, repo_info: dict, evidence: dict, diff_text: str, collected_at: str
) -> dict:
    repository = repo_info["full_name"]
    return {
        "case_id": case_id_for(repository, pr["number"]),
        "kind": "real",
        "source_url": pr["html_url"],
        "repository": repository,
        "pr_number": pr["number"],
        "title": pr["title"],
        "description": pr.get("body") or "",
        "base_ref": pr["base"]["ref"],
        "base_sha": pr["base"]["sha"],
        "head_sha": pr["head"]["sha"],
        "created_at": pr["created_at"],
        "merged_at": pr["merged_at"],
        "additions": pr["additions"],
        "deletions": pr["deletions"],
        "changed_files": pr["changed_files"],
        "collected_at": collected_at,
        "ai_evidence": evidence,
        "repository_info": {
            "stars": repo_info.get("stargazers_count"),
            "license": (repo_info.get("license") or {}).get("spdx_id"),
            "language": repo_info.get("language"),
        },
        "diff_file": "pr.diff",
        "diff_sha256": sha256_text(diff_text),
        "diff_source": f"/repos/{repository}/compare/{pr['base']['sha']}...{pr['head']['sha']}",
    }


# --- storage --------------------------------------------------------------------------


def _read_exact(path: Path) -> str:
    # newline="" keeps "\r\n" as-is, so checksums match the downloaded text.
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def _write_atomic(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    temporary.replace(path)


def save_case(out_dir: Path, metadata: dict, diff_text: str) -> None:
    case_dir = out_dir / metadata["case_id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    _write_atomic(case_dir / "pr.diff", diff_text)
    # Written last: a case directory without metadata.json is incomplete.
    _write_atomic(case_dir / "metadata.json", json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")


def load_cases(out_dir: Path) -> dict:
    """Complete cases (metadata present and diff checksum matching), by case ID."""
    cases = {}
    if not out_dir.exists():
        return cases
    for metadata_path in sorted(out_dir.glob("*/metadata.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        diff_path = metadata_path.parent / metadata["diff_file"]
        if diff_path.exists() and sha256_text(_read_exact(diff_path)) == metadata["diff_sha256"]:
            cases[metadata["case_id"]] = metadata
    return cases


def load_exclusions(out_dir: Path) -> dict:
    path = out_dir / "exclusions.jsonl"
    if not path.exists():
        return {}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return {row["case_id"]: row["reason"] for row in rows}


def record_exclusion(out_dir: Path, row: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "exclusions.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def write_manifest(path: Path, cases: dict) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        for case_id in sorted(cases):
            metadata = cases[case_id]
            writer.writerow({
                "case_id": case_id,
                "source_url": metadata["source_url"],
                "repository": metadata["repository"],
                "pr_number": metadata["pr_number"],
                "agent_app": metadata["ai_evidence"]["app_slug"],
                "title": metadata["title"],
                "base_sha": metadata["base_sha"],
                "head_sha": metadata["head_sha"],
                "diff_sha256": metadata["diff_sha256"],
                "collected_at": metadata["collected_at"],
            })


# --- collection ---------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def collect(
    client: GitHubClient,
    out_dir: Path,
    settings: Settings = Settings(),
    agents: list = AGENT_APPS,
    now: Callable[[], str] = _utc_now,
    log: Callable[[str], None] = lambda message: None,
) -> dict:
    """Search, filter and save cases. Returns a report of totals and exclusions."""
    cases = load_cases(out_dir)
    excluded = load_exclusions(out_dir)
    per_repo = Counter(m["repository"] for m in cases.values())
    per_agent = Counter(m["ai_evidence"]["app_slug"] for m in cases.values())
    repo_cache: dict = {}
    seen: set = set()
    report = {"started_at": now(), "settings": asdict(settings), "agents": {}, "duplicates_skipped": 0}

    for agent in agents:
        stats = {"query": search_query(agent, settings), "candidates_seen": 0,
                 "already_collected": 0, "collected": 0, "excluded": Counter()}
        report["agents"][agent.slug] = stats
        params = {"q": stats["query"], "sort": "created", "order": "asc", "per_page": 100}
        for item in client.paginate("/search/issues", params, max_pages=settings.max_search_pages):
            if per_agent[agent.slug] >= settings.per_agent:
                break
            repository = item["repository_url"].split("/repos/", 1)[1]
            case_id = case_id_for(repository, item["number"])
            if case_id in seen:
                report["duplicates_skipped"] += 1
                continue
            seen.add(case_id)
            stats["candidates_seen"] += 1
            if case_id in cases:
                stats["already_collected"] += 1
                continue
            if case_id in excluded:
                stats["excluded"][excluded[case_id]] += 1
                continue

            reason, metadata, diff_text = _evaluate_candidate(
                client, agent, repository, item, settings, per_repo, repo_cache, now
            )
            if reason is not None:
                stats["excluded"][reason] += 1
                if not _is_transient(reason):
                    record_exclusion(out_dir, {
                        "case_id": case_id, "source_url": item["html_url"],
                        "agent_app": agent.slug, "reason": reason, "recorded_at": now(),
                    })
                log(f"excluded {case_id}: {reason}")
                continue

            save_case(out_dir, metadata, diff_text)
            cases[case_id] = metadata
            per_repo[repository] += 1
            per_agent[agent.slug] += 1
            stats["collected"] += 1
            log(f"collected {case_id}")
        stats["excluded"] = dict(stats["excluded"])

    report["finished_at"] = now()
    report["total_cases"] = len(cases)
    report["cases_per_agent"] = dict(Counter(m["ai_evidence"]["app_slug"] for m in cases.values()))
    report["repositories"] = len({m["repository"] for m in cases.values()})
    report["max_cases_in_one_repository"] = max(per_repo.values(), default=0)
    report["rate_limit_waits"] = client.rate_limit_waits
    return report


def _evaluate_candidate(client, agent, repository, item, settings, per_repo, repo_cache, now):
    """Return (exclusion_reason, metadata, diff_text) for one search result."""
    if bot_evidence(item.get("user") or {}, agent) is None:
        return "author_not_verified_bot", None, None
    if per_repo[repository] >= settings.max_per_repo:
        return "repository_cap_reached", None, None
    try:
        if repository not in repo_cache:
            repo_cache[repository] = client.get_json(f"/repos/{repository}")
        repo_info = repo_cache[repository]
        reason = repository_exclusion(repo_info, settings)
        if reason:
            return reason, None, None

        pr = client.get_json(f"/repos/{repository}/pulls/{item['number']}")
        evidence = bot_evidence(pr["user"], agent)
        if evidence is None:
            return "author_not_verified_bot", None, None
        reason = pull_request_exclusion(pr, settings)
        if reason:
            return reason, None, None

        diff_text = client.get_text(
            f"/repos/{repository}/compare/{pr['base']['sha']}...{pr['head']['sha']}"
        )
    except ApiError as error:
        return f"api_error_{error.status}", None, None

    reason = diff_exclusion(diff_text, pr, settings)
    if reason:
        return reason, None, None
    return None, build_metadata(pr, repo_info, evidence, diff_text, now()), diff_text


def refetch_from_manifest(client: GitHubClient, manifest_path: Path, out_dir: Path,
                          now: Callable[[], str] = _utc_now) -> dict:
    """Re-download the exact cases in a manifest and verify each diff checksum."""
    agents = {agent.slug: agent for agent in AGENT_APPS}
    results = Counter()
    with open(manifest_path, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        repository, number = row["repository"], int(row["pr_number"])
        try:
            pr = client.get_json(f"/repos/{repository}/pulls/{number}")
            repo_info = client.get_json(f"/repos/{repository}")
            diff_text = client.get_text(
                f"/repos/{repository}/compare/{row['base_sha']}...{row['head_sha']}"
            )
        except ApiError as error:
            results[f"api_error_{error.status}"] += 1
            continue
        evidence = bot_evidence(pr["user"], agents[row["agent_app"]])
        if evidence is None:
            results["author_not_verified_bot"] += 1
        elif sha256_text(diff_text) != row["diff_sha256"]:
            results["checksum_mismatch"] += 1
        else:
            save_case(out_dir, build_metadata(pr, repo_info, evidence, diff_text, now()), diff_text)
            results["verified"] += 1
    return {"manifest_rows": len(rows), **results}


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--from-manifest", type=Path, default=None,
                        help="Re-fetch exactly the cases in this manifest and verify checksums.")
    parser.add_argument("--per-agent", type=int, default=Settings.per_agent)
    parser.add_argument("--max-per-repo", type=int, default=Settings.max_per_repo)
    parser.add_argument("--min-stars", type=int, default=Settings.min_stars)
    parser.add_argument("--since", default=Settings.since)
    parser.add_argument("--until", default=Settings.until)
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is not set. Export a GitHub token with public read access; "
              "it is only read from the environment and is never printed or saved.", file=sys.stderr)
        return 2

    def log(message: str) -> None:
        print(message, file=sys.stderr)

    client = GitHubClient(token, log=log)
    if args.from_manifest:
        print(json.dumps(refetch_from_manifest(client, args.from_manifest, args.out), indent=2))
        return 0

    settings = Settings(since=args.since, until=args.until, per_agent=args.per_agent,
                        max_per_repo=args.max_per_repo, min_stars=args.min_stars)
    report = collect(client, args.out, settings, log=log)
    write_manifest(args.manifest, load_cases(args.out))
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "total_cases", "cases_per_agent", "repositories", "max_cases_in_one_repository",
        "duplicates_skipped", "rate_limit_waits")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
