"""Terminal renderer (doc §7.7): compact rich summary.

Quality is honestly reported as unmeasured until a --quality map is supplied
(Phase 3) rather than guessed at.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from wattage.models import Report


def render_terminal(report: Report, console: Console | None = None) -> None:
    console = console or Console()

    headline = (
        f"[bold]Token Efficiency:[/bold] {report.score.grade} ({report.score.efficiency})"
        f"   [bold]Total cost:[/bold] ${report.total_dollars:.4f}"
    )
    if not report.score.quality_measured:
        headline += "\n[dim]quality: unmeasured[/dim]"
    console.print(Panel(headline, title=f"⚡ wattage — {report.trace_source}", expand=False))

    table = Table(title="Token breakdown")
    table.add_column("Category")
    table.add_column("Tokens", justify="right")
    for category, tokens in report.token_breakdown.items():
        table.add_row(category, str(tokens))
    console.print(table)

    if report.findings:
        findings_table = Table(title="Findings")
        findings_table.add_column("Detector")
        findings_table.add_column("Severity")
        findings_table.add_column("Wasted $", justify="right")
        findings_table.add_column("Fix")
        for f in report.findings:
            findings_table.add_row(f.id, f.severity.value, f"${f.wasted_dollars:.4f}", f.fix)
        console.print(findings_table)
    else:
        console.print("[dim]No findings — this trace looks efficient.[/dim]")

    console.print(f"[dim]pricing: {report.pricing_version}[/dim]")
