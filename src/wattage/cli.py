from pathlib import Path
from typing import Annotated

import typer

from wattage import __version__
from wattage.render.json_report import render_json
from wattage.render.terminal import render_terminal
from wattage.report import build_report

app = typer.Typer(
    name="wattage",
    help="A token-spend profiler and cost-regression gate for AI agents.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"wattage {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """wattage: see where your tokens burn."""


@app.command()
def report(
    source: Annotated[Path, typer.Argument(help="Path to an OTLP JSON trace file.")],
    pricing: Annotated[
        Path | None, typer.Option(help="Path to a pricing.yaml override.")
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print the full machine-readable JSON report.")
    ] = False,
    html_output: Annotated[
        Path | None,
        typer.Option("--html", help="Write a self-contained HTML flame graph (Phase 3)."),
    ] = None,
) -> None:
    """Ingest a trace and print a priced, findings-quantified report."""
    if html_output is not None:
        raise typer.BadParameter(
            "--html isn't implemented yet — the flame graph renderer lands in Phase 3."
        )
    report_obj = build_report(str(source), pricing_override=str(pricing) if pricing else None)
    if json_output:
        typer.echo(render_json(report_obj))
    else:
        render_terminal(report_obj)


@app.command()
def score(
    source: Annotated[Path, typer.Argument(help="Path to an OTLP JSON trace file.")],
    pricing: Annotated[
        Path | None, typer.Option(help="Path to a pricing.yaml override.")
    ] = None,
) -> None:
    """Print just the Token Efficiency score and dollar headline."""
    report_obj = build_report(str(source), pricing_override=str(pricing) if pricing else None)
    s = report_obj.score
    typer.echo(f"{s.grade} ({s.efficiency}) · ${s.recoverable_dollars:.4f} recoverable")


if __name__ == "__main__":
    app()
