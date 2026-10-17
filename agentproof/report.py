"""Render an AuditReport as HTML (Jinja2) or JSON.

Every renderer redacts the report first (see agentproof.redaction).
SARIF output lives in agentproof.sarif; terminal output in agentproof.cli.
"""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from agentproof import __version__
from agentproof.redaction import redact_report
from agentproof.schema import AuditReport, Finding

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Increase when the JSON structure changes in a way consumers must notice.
JSON_SCHEMA_VERSION = 1


def render_html(report: AuditReport) -> str:
    report = redact_report(report)
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("report.html")
    findings_sorted = sorted(
        report.findings,
        key=lambda f: ["critical", "high", "medium", "low"].index(f.severity.value),
    )
    return template.render(
        report=report,
        findings=findings_sorted,
        counts=report.counts_by_severity,
    )


def _finding_to_dict(finding: Finding) -> dict:
    return {
        "rule_id": finding.rule_id,
        "severity": finding.severity.value,
        "title": finding.title,
        "file_path": finding.file_path,
        "files": list(finding.paths) or [finding.file_path],
        # "old": line numbers refer to the base version (deleted lines).
        # "new": line numbers refer to the audited branch (added lines).
        # null: the finding is about whole files, not lines.
        "side": finding.side.value if finding.side else None,
        "line_number": finding.line_number,
        "end_line_number": finding.end_line_number,
        "location": finding.location,
        "evidence": finding.evidence,
        "recommendation": finding.recommendation,
    }


def render_json(report: AuditReport) -> str:
    report = redact_report(report)
    data = {
        "schema_version": JSON_SCHEMA_VERSION,
        "tool": {"name": "agentproof", "version": __version__},
        "base": report.base,
        "branch": report.branch,
        "task": report.task,
        "config_source": report.config_source,
        "risk_score": report.risk_score,
        "recommendation": report.recommendation.value,
        "counts_by_severity": report.counts_by_severity,
        "changed_files": report.changed_files,
        "findings": [_finding_to_dict(f) for f in report.findings],
        "ignored_findings": [_finding_to_dict(f) for f in report.ignored_findings],
    }
    # Only present with --llm-verify, so the default output does not change.
    summary = report.llm_verification
    if summary is not None:
        data["llm_suppressed_findings"] = [_finding_to_dict(f) for f in report.llm_suppressed_findings]
        data["llm_verification"] = {
            "model": summary.model,
            "url": summary.url,
            "ollama_version": summary.ollama_version,
            "fallback": summary.fallback,
            "decisions": [
                {
                    "rule_id": d.rule_id,
                    "location": d.location,
                    "suppressed": d.suppressed,
                    "status": d.status,
                    "reason": d.reason,
                    "seconds": d.seconds,
                }
                for d in summary.decisions
            ],
        }
    return json.dumps(data, indent=2) + "\n"
