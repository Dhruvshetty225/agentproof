"""Render an AuditReport as SARIF 2.1.0 (Static Analysis Results Interchange Format).

How AgentProof maps onto SARIF:

* Each rule becomes a ``reportingDescriptor``. Its descriptions come from the
  rule module's docstring.
* Severity -> SARIF level: critical and high -> "error", medium -> "warning",
  low -> "note". The original severity is kept in ``properties.severity``.
* File locations are repository-relative URIs with ``uriBaseId`` "%SRCROOT%".
* Added-line findings get a ``region`` with line numbers from the audited branch.
* Deleted-line findings point at the file only, with no region. Their line
  numbers come from the base version; putting them on the current file would
  point at unrelated lines. The base line numbers are stated in the message
  and kept in ``properties.baseStartLine`` / ``properties.baseEndLine``.
* Findings about whole files point at each file, without a region.
* Findings silenced by ``agentproof: ignore[...]`` are included with an
  "inSource" suppression, so tools show them as suppressed, not as open.
* With --llm-verify, findings the local model judged not risky are included
  with an "external" suppression whose justification is the model's reason,
  and the run's ``properties.llmVerification`` records the model and any
  fallback. Without --llm-verify, neither appears.
* The run's ``properties`` hold the risk score and recommendation.

Text is redacted before rendering, like every other output format.
"""

from __future__ import annotations

import inspect
import json
from urllib.parse import quote

from agentproof import __version__
from agentproof.redaction import redact_report
from agentproof.rules import ALL_RULES
from agentproof.schema import AuditReport, DiffSide, Finding, Severity

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA_URI = "https://json.schemastore.org/sarif-2.1.0.json"
INFORMATION_URI = "https://github.com/Dhruvshetty225/agentproof"

_LEVELS = {
    Severity.CRITICAL: "error",
    Severity.HIGH: "error",
    Severity.MEDIUM: "warning",
    Severity.LOW: "note",
}
_RULE_IDS = [rule.RULE_ID for rule in ALL_RULES]


def _rule_descriptor(rule_module) -> dict:
    doc = inspect.getdoc(rule_module) or rule_module.RULE_ID
    return {
        "id": rule_module.RULE_ID,
        "shortDescription": {"text": doc.splitlines()[0]},
        "fullDescription": {"text": doc},
        "helpUri": INFORMATION_URI,
    }


def _artifact_location(path: str) -> dict:
    return {"uri": quote(path), "uriBaseId": "%SRCROOT%"}


def _locations(finding: Finding) -> list[dict]:
    if finding.side is DiffSide.NEW and finding.line_number is not None:
        region = {"startLine": finding.line_number}
        if finding.end_line_number is not None:
            region["endLine"] = finding.end_line_number
        return [{
            "physicalLocation": {
                "artifactLocation": _artifact_location(finding.file_path),
                "region": region,
            }
        }]
    paths = finding.paths or (finding.file_path,)
    return [{"physicalLocation": {"artifactLocation": _artifact_location(p)}} for p in paths]


def _message(finding: Finding, base: str) -> str:
    parts = [f"{finding.title}."]
    if finding.side is DiffSide.OLD and finding.lines is not None:
        parts.append(
            f"Deleted line(s) {finding.lines} of {finding.file_path} as numbered in the "
            f"base version ({base}); these numbers do not refer to the current file."
        )
    parts.append(f"Evidence: {finding.evidence}")
    parts.append(finding.recommendation)
    return " ".join(parts)


_IGNORE_SUPPRESSION = {"kind": "inSource", "justification": "agentproof: ignore directive on this line"}


def _llm_suppression(model: str, reason: str) -> dict:
    return {"kind": "external", "justification": f"Local LLM verifier ({model}) judged it not risky: {reason}"}


def _result(finding: Finding, base: str, suppression: dict | None = None) -> dict:
    result = {
        "ruleId": finding.rule_id,
        "level": _LEVELS[finding.severity],
        "message": {"text": _message(finding, base)},
        "locations": _locations(finding),
        "properties": {"severity": finding.severity.value},
    }
    if finding.rule_id in _RULE_IDS:
        result["ruleIndex"] = _RULE_IDS.index(finding.rule_id)
    if finding.side is DiffSide.OLD and finding.line_number is not None:
        result["properties"]["diffSide"] = "old"
        result["properties"]["baseStartLine"] = finding.line_number
        result["properties"]["baseEndLine"] = finding.end_line_number or finding.line_number
    if suppression is not None:
        result["suppressions"] = [suppression]
    return result


def render_sarif(report: AuditReport) -> str:
    report = redact_report(report)
    results = [_result(f, report.base) for f in report.findings]
    results += [_result(f, report.base, _IGNORE_SUPPRESSION) for f in report.ignored_findings]
    summary = report.llm_verification
    if summary is not None:
        reasons = {(d.rule_id, d.location): d.reason for d in summary.decisions if d.suppressed}
        results += [
            _result(f, report.base, _llm_suppression(summary.model, reasons.get((f.rule_id, f.location), "")))
            for f in report.llm_suppressed_findings
        ]
    sarif = {
        "$schema": SARIF_SCHEMA_URI,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "AgentProof",
                        "version": __version__,
                        "informationUri": INFORMATION_URI,
                        "rules": [_rule_descriptor(rule) for rule in ALL_RULES],
                    }
                },
                "results": results,
                "properties": {
                    "base": report.base,
                    "branch": report.branch,
                    "riskScore": report.risk_score,
                    "recommendation": report.recommendation.value,
                    "configSource": report.config_source,
                },
            }
        ],
    }
    if summary is not None:
        sarif["runs"][0]["properties"]["llmVerification"] = {
            "model": summary.model,
            "ollamaVersion": summary.ollama_version,
            "fallback": summary.fallback,
            "suppressed": len(report.llm_suppressed_findings),
        }
    return json.dumps(sarif, indent=2) + "\n"
