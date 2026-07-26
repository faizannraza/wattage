"""Terminal renderer (doc §7.7): compact rich summary.

Quality is honestly reported as unmeasured until a --quality map is supplied
(Phase 3) rather than guessed at.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from wattage.models import Report
from wattage.render.format import format_dollars

# A bare Console() auto-detects the live terminal's width, so the exact same
# report renders at a different box width for every user/environment (and
# differently again for a non-tty/piped invocation) -- undermining the
# "share a screenshot, docs show exactly this" premise the report/README are
# built around. Pinned to a fixed width instead, so output is reproducible
# regardless of the caller's terminal.
_DEFAULT_WIDTH = 100


def render_terminal(report: Report, console: Console | None = None) -> None:
    console = console or Console(width=_DEFAULT_WIDTH)

    headline = (
        f"[bold]Token Efficiency:[/bold] {report.score.grade} ({report.score.efficiency})"
        f"   [bold]Total cost:[/bold] ${report.total_dollars:.4f}"
    )
    if not report.score.quality_measured:
        headline += "\n[dim]quality: unmeasured[/dim]"
    if report.unpriced_calls:
        models = ", ".join(report.unpriced_models)
        warning = (
            f"[bold yellow]⚠ {report.unpriced_calls} call(s) unpriced[/bold yellow] "
            f"(no registry entry for {models}) — cost and score below are incomplete"
        )
        headline = f"{warning}\n{headline}"
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
            findings_table.add_row(f.id, f.severity.value, format_dollars(f.wasted_dollars), f.fix)
        console.print(findings_table)
    elif report.unpriced_calls:
        console.print(
            "[dim]No findings on the priced portion of this trace — "
            f"{report.unpriced_calls} call(s) could not be priced, so this is not "
            "a confirmed-efficient trace.[/dim]"
        )
    else:
        console.print("[dim]No findings — this trace looks efficient.[/dim]")

    console.print(f"[dim]pricing: {report.pricing_version}[/dim]")
