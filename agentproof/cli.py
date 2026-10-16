"""AgentProof command-line interface."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from agentproof.config import ConfigError, load_config
from agentproof.engine import run_audit
from agentproof.redaction import redact_report
from agentproof.report import write_html_report
from agentproof.schema import AuditReport, MergeRecommendation, Severity

app = typer.Typer(
    help="AgentProof: audit AI-generated code changes before merge.",
    no_args_is_help=True,
)
console = Console()

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


@app.command()
def audit(
    repo: str = typer.Option(..., "--repo", help="Path to the git repository to audit."),
    base: str = typer.Option("main", "--base", help="Base branch to compare against."),
    branch: str = typer.Option(..., "--branch", help="Branch containing the changes to audit."),
    task: Optional[str] = typer.Option(
        None, "--task", help="Description of the intended task, used to flag unrelated changes."
    ),
    output: str = typer.Option(
        "agentproof-report.html", "--output", help="Path to write the HTML report."
    ),
    config_path: Optional[str] = typer.Option(
        None,
        "--config",
        help="Path to a .agentproof.toml file. Default: .agentproof.toml on the base branch.",
    ),
) -> None:
    """Audit the diff between BASE and BRANCH in REPO and generate a risk report."""
    try:
        config = load_config(repo, base, config_path)
    except ConfigError as exc:
        console.print(f"[bold red]Configuration error:[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=2)

    report = run_audit(repo_path=repo, base=base, branch=branch, task=task, config=config)

    _print_terminal_report(report)

    html_path = write_html_report(report, output_path=output)
    console.print(f"\n[bold]HTML report written to:[/bold] {html_path}\n")

    if report.recommendation == MergeRecommendation.REJECT:
        raise typer.Exit(code=1)


@app.command()
def version() -> None:
    """Print the installed AgentProof version."""
    from agentproof import __version__

    console.print(f"agentproof {__version__}")


def _print_terminal_report(report: AuditReport) -> None:
    # Text that comes from the repository (evidence, paths, task) is passed
    # through escape() so Rich does not treat "[...]" in code as markup.
    report = redact_report(report)
    console.print()
    console.print(
        Panel.fit(
            f"[bold]{escape(report.branch)}[/bold] -> [bold]{escape(report.base)}[/bold]"
            + (f"\ntask: \"{escape(report.task)}\"" if report.task else ""),
            title="AgentProof Audit",
            border_style="cyan",
        )
    )

    rec_style = _RECOMMENDATION_STYLE[report.recommendation]
    console.print(
        f"\nRisk Score: [bold]{report.risk_score}/100[/bold]   "
        f"Recommendation: [{rec_style}]{report.recommendation.value.upper()}[/{rec_style}]"
    )

    counts = report.counts_by_severity
    console.print(
        f"Findings: {len(report.findings)}  "
        f"([bold red]critical={counts['critical']}[/bold red] "
        f"[red]high={counts['high']}[/red] "
        f"[yellow]medium={counts['medium']}[/yellow] "
        f"[blue]low={counts['low']}[/blue])"
    )

    console.print(f"Changed files: {escape(', '.join(report.changed_files)) or '(none)'}")
    console.print(f"Config: {escape(report.config_source)}")
    if report.ignored_findings:
        ignored = ", ".join(f"{f.rule_id} at {f.location}" for f in report.ignored_findings)
        console.print(
            f"Ignored by inline directives ({len(report.ignored_findings)}): "
            f"{escape(ignored)}"
        )
    console.print()

    if not report.findings:
        console.print("[bold green]No findings. This change looks safe to merge.[/bold green]")
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

    console.print(table)


if __name__ == "__main__":
    app()
