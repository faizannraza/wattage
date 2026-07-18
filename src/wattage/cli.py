from pathlib import Path
from typing import Annotated

import typer

from wattage import __version__
from wattage.render.badge import render_badge
from wattage.render.html import render_html
from wattage.render.json_report import render_json
from wattage.render.terminal import render_terminal
from wattage.report import build_report, build_trace_and_report

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
    quality: Annotated[
        Path | None,
        typer.Option(help="Path to a quality.json map; enables quality-gated findings."),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print the full machine-readable JSON report.")
    ] = False,
    html_output: Annotated[
        Path | None,
        typer.Option("--html", help="Write a self-contained HTML flame graph."),
    ] = None,
) -> None:
    """Ingest a trace and print a priced, findings-quantified report."""
    if html_output is not None:
        trace, report_obj = build_trace_and_report(
            str(source),
            pricing_override=str(pricing) if pricing else None,
            quality_file=str(quality) if quality else None,
        )
        html_output.write_text(render_html(trace, report_obj), encoding="utf-8")
        typer.echo(f"wrote {html_output}")
        return
    report_obj = build_report(
        str(source),
        pricing_override=str(pricing) if pricing else None,
        quality_file=str(quality) if quality else None,
    )
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
    quality: Annotated[
        Path | None,
        typer.Option(help="Path to a quality.json map; enables quality-gated findings."),
    ] = None,
) -> None:
    """Print just the Token Efficiency score and dollar headline."""
    report_obj = build_report(
        str(source),
        pricing_override=str(pricing) if pricing else None,
        quality_file=str(quality) if quality else None,
    )
    s = report_obj.score
    typer.echo(f"{s.grade} ({s.efficiency}) · ${s.recoverable_dollars:.4f} recoverable")


@app.command()
def badge(
    source: Annotated[Path, typer.Argument(help="Path to an OTLP JSON trace file.")],
    pricing: Annotated[
        Path | None, typer.Option(help="Path to a pricing.yaml override.")
    ] = None,
    quality: Annotated[
        Path | None,
        typer.Option(help="Path to a quality.json map; enables quality-gated findings."),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", help="Write the SVG to this file instead of stdout.")
    ] = None,
) -> None:
    """Emit a Token Efficiency SVG badge."""
    report_obj = build_report(
        str(source),
        pricing_override=str(pricing) if pricing else None,
        quality_file=str(quality) if quality else None,
    )
    svg = render_badge(report_obj)
    if out is not None:
        out.write_text(svg, encoding="utf-8")
    else:
        typer.echo(svg)


if __name__ == "__main__":
    app()
