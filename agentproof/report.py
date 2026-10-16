"""Render an AuditReport to an HTML file using Jinja2."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from agentproof.redaction import redact_report
from agentproof.schema import AuditReport

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


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


def write_html_report(report: AuditReport, output_path: str = "agentproof-report.html") -> str:
    html = render_html(report)
    path = Path(output_path)
    path.write_text(html, encoding="utf-8")
    return str(path.resolve())
