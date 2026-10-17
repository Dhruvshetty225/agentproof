"""AgentProof command-line interface.

Output rules for ``agentproof audit``:

* ``--format`` picks one of terminal (default), html, json or sarif. If it is
  omitted and ``--output`` ends in .html/.htm, .json or .sarif, the format is
  taken from that extension.
* The report goes to standard output, unless ``--output PATH`` is given, in
  which case it is written to that file instead.
* Status messages and errors always go to standard error, so standard output
  holds nothing but the report (e.g. ``--format json > report.json`` works).

``--llm-verify`` (off by default) asks a local Ollama model whether each
finding is actually risky; see agentproof/llm_verify.py. If Ollama cannot be
reached, the audit still runs and the report says it is rules-only.

Exit codes: 0 approve or review, 1 reject, 2 usage, configuration, git or
file errors.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from git.exc import GitError, ODBError
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from agentproof.config import ConfigError, load_config
from agentproof.engine import run_audit
from agentproof.llm_verify import (
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT,
    DEFAULT_URL,
    LLMVerifier,
    LocalOnlyError,
    OllamaClient,
)
from agentproof.redaction import redact_report
from agentproof.report import render_html, render_json
from agentproof.sarif import render_sarif
from agentproof.schema import AuditReport, MergeRecommendation, Severity

app = typer.Typer(
    help="AgentProof: audit AI-generated code changes before merge.",
    no_args_is_help=True,
)
console = Console()  # the terminal report (standard output)
status = Console(stderr=True)  # errors and status messages (standard error)

# Width used when a terminal report is written to a file instead of a screen.
_FILE_REPORT_WIDTH = 120

_SEVERITY_STYLE = {
    Severity.CRITICAL: "bold white on red",
    Severity.HIGH: "bold red",
    Severity.MEDIUM: "bold yellow",
    Severity.LOW: "bold blue",
}

_RECOMMENDATION_STYLE = {
    MergeRecommendation.APPROVE: "bold green",
    MergeRecommendation.REVIEW: "bold yellow",
    MergeRecommendation.REJECT: "bold red",
}

_SEVERITY_ORDER = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]


class OutputFormat(str, Enum):
    TERMINAL = "terminal"
    HTML = "html"
    JSON = "json"
    SARIF = "sarif"


_FORMAT_BY_EXTENSION = {
    ".html": OutputFormat.HTML,
    ".htm": OutputFormat.HTML,
    ".json": OutputFormat.JSON,
    ".sarif": OutputFormat.SARIF,
}

_RENDERERS = {
    OutputFormat.HTML: render_html,
    OutputFormat.JSON: render_json,
    OutputFormat.SARIF: render_sarif,
}


def _resolve_format(chosen: Optional[OutputFormat], output: Optional[str]) -> OutputFormat:
    if chosen is not None:
        return chosen
    if output is not None:
        return _FORMAT_BY_EXTENSION.get(Path(output).suffix.lower(), OutputFormat.TERMINAL)
    return OutputFormat.TERMINAL


def _fail(prefix: str, error: Exception) -> None:
    # soft_wrap keeps long messages on one line so they can be copied or grepped.
    status.print(f"[bold red]{prefix}:[/bold red] {escape(str(error))}", soft_wrap=True)
    raise typer.Exit(code=2)


@app.command()
def audit(
    repo: str = typer.Option(..., "--repo", help="Path to the git repository to audit."),
    base: str = typer.Option("main", "--base", help="Base branch or commit to compare against."),
    branch: str = typer.Option(
        ..., "--branch", help="Branch or commit containing the changes to audit."
    ),
    task: Optional[str] = typer.Option(
        None, "--task", help="Description of the intended task, used to flag unrelated changes."
    ),
    output_format: Optional[OutputFormat] = typer.Option(
        None,
        "--format",
        case_sensitive=False,
        help="Report format. Default: terminal, or inferred from the --output extension.",
    ),
    output: Optional[str] = typer.Option(
        None, "--output", help="Write the report to this file instead of standard output."
    ),
    config_path: Optional[str] = typer.Option(
        None,
        "--config",
        help="Path to a .agentproof.toml file. Default: .agentproof.toml on the base branch.",
    ),
    llm_verify: bool = typer.Option(
        False,
        "--llm-verify",
        help="Ask a local Ollama model whether each finding is actually risky (off by default).",
    ),
    llm_model: str = typer.Option(DEFAULT_MODEL, "--llm-model", help="Local Ollama model to use."),
    llm_url: str = typer.Option(
        DEFAULT_URL, "--llm-url", help="Local Ollama server; must be on this machine."
    ),
    llm_timeout: float = typer.Option(
        DEFAULT_TIMEOUT, "--llm-timeout", help="Seconds to wait for each answer from the model."
    ),
) -> None:
    """Audit the changes BRANCH made since it diverged from BASE in REPO."""
    report_format = _resolve_format(output_format, output)
    verifier = None
    if llm_verify:
        try:
            verifier = LLMVerifier(OllamaClient(llm_url, llm_model, llm_timeout))
        except LocalOnlyError as error:
            _fail("LLM verifier", error)
    try:
        config = load_config(repo, base, config_path)
        report = run_audit(
            repo_path=repo, base=base, branch=branch, task=task, config=config, verifier=verifier
        )
    except ConfigError as error:
        _fail("Configuration error", error)
    except (GitError, ODBError) as error:
        _fail(
            "Git error (check --repo, --base and --branch; CI checkouts need full history)",
            error,
        )

    if report.llm_verification is not None and report.llm_verification.fallback:
        status.print(
            f"[yellow]LLM verifier:[/yellow] {escape(report.llm_verification.fallback)}",
            soft_wrap=True,
        )

    try:
        _emit(report, report_format, output)
    except OSError as error:
        _fail(f"Cannot write report to {output}", error)

    if report.recommendation == MergeRecommendation.REJECT:
        raise typer.Exit(code=1)


def _emit(report: AuditReport, report_format: OutputFormat, output: Optional[str]) -> None:
    if output is None:
        if report_format is OutputFormat.TERMINAL:
            _print_terminal_report(report)
        else:
            typer.echo(_RENDERERS[report_format](report), nl=False)
        return

    with open(output, "w", encoding="utf-8") as handle:
        if report_format is OutputFormat.TERMINAL:
            file_console = Console(file=handle, width=_FILE_REPORT_WIDTH, no_color=True)
            _print_terminal_report(report, file_console)
        else:
            handle.write(_RENDERERS[report_format](report))
    status.print(
        f"{report_format.value} report written to {escape(str(Path(output).resolve()))}",
        soft_wrap=True,
    )


@app.command()
def version() -> None:
    """Print the installed AgentProof version."""
    from agentproof import __version__

    console.print(f"agentproof {__version__}")


def _print_terminal_report(report: AuditReport, out: Optional[Console] = None) -> None:
    out = out or console
    # Text that comes from the repository (evidence, paths, task) is passed
    # through escape() so Rich does not treat "[...]" in code as markup.
    report = redact_report(report)
    out.print()
    out.print(
        Panel.fit(
            f"[bold]{escape(report.branch)}[/bold] -> [bold]{escape(report.base)}[/bold]"
            + (f"\ntask: \"{escape(report.task)}\"" if report.task else ""),
            title="AgentProof Audit",
            border_style="cyan",
        )
    )

    rec_style = _RECOMMENDATION_STYLE[report.recommendation]
    out.print(
        f"\nRisk Score: [bold]{report.risk_score}/100[/bold]   "
        f"Recommendation: [{rec_style}]{report.recommendation.value.upper()}[/{rec_style}]"
    )

    counts = report.counts_by_severity
    out.print(
        f"Findings: {len(report.findings)}  "
        f"([bold red]critical={counts['critical']}[/bold red] "
        f"[red]high={counts['high']}[/red] "
        f"[yellow]medium={counts['medium']}[/yellow] "
        f"[blue]low={counts['low']}[/blue])"
    )

    out.print(f"Changed files: {escape(', '.join(report.changed_files)) or '(none)'}")
    out.print(f"Config: {escape(report.config_source)}")
    if report.ignored_findings:
        ignored = ", ".join(f"{f.rule_id} at {f.location}" for f in report.ignored_findings)
        out.print(
            f"Ignored by inline directives ({len(report.ignored_findings)}): "
            f"{escape(ignored)}"
        )
    _print_llm_summary(report, out)
    out.print()

    if not report.findings:
        if report.llm_suppressed_findings:
            out.print(
                "[bold green]No findings left after local LLM verification.[/bold green] "
                "The suppressed findings are listed above. This does not prove the change "
                "is safe; review it as usual."
            )
        else:
            out.print(
                "[bold green]No findings from AgentProof's rules.[/bold green] "
                "This does not prove the change is safe; review it as usual."
            )
        return

    table = Table(show_lines=True, expand=True)
    table.add_column("Severity", no_wrap=True)
    table.add_column("Rule", no_wrap=True)
    table.add_column("Location")
    table.add_column("Finding")
    table.add_column("Evidence")
    table.add_column("Recommendation")

    sorted_findings = sorted(report.findings, key=lambda f: _SEVERITY_ORDER.index(f.severity))
    for finding in sorted_findings:
        style = _SEVERITY_STYLE[finding.severity]
        table.add_row(
            f"[{style}]{finding.severity.value.upper()}[/{style}]",
            finding.rule_id,
            escape(finding.location),
            escape(finding.title),
            escape(finding.evidence),
            escape(finding.recommendation),
        )

    out.print(table)


def _print_llm_summary(report: AuditReport, out: Console) -> None:
    summary = report.llm_verification
    if summary is None:
        return
    suppressed = len(report.llm_suppressed_findings)
    out.print(
        f"Local LLM verification ({escape(summary.model)}): "
        f"{suppressed} suppressed, {len(summary.decisions) - suppressed} kept"
    )
    if summary.fallback:
        out.print(f"[yellow]LLM fallback:[/yellow] {escape(summary.fallback)}")
    for decision in summary.decisions:
        if decision.suppressed:
            out.print(
                f"  suppressed {decision.rule_id} at {escape(decision.location)}: "
                f"{escape(decision.reason)}"
            )


if __name__ == "__main__":
    app()
