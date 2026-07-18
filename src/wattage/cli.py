from pathlib import Path
from typing import Annotated

import typer

from wattage import __version__
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
) -> None:
    """Ingest a trace and print a priced report."""
    report_obj = build_report(str(source), pricing_override=str(pricing) if pricing else None)
    render_terminal(report_obj)


if __name__ == "__main__":
    app()
