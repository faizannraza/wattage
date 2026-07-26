import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, TypeVar

import typer
import yaml

from wattage import __version__
from wattage.adapters.base import AdapterError
from wattage.ci import CIConfigError, parse_fail_on, run_ci
from wattage.config import WattageConfig, WattageConfigError, load_config
from wattage.pricing.registry import PricingConfigError
from wattage.render.badge import render_badge
from wattage.render.format import format_dollars
from wattage.render.html import render_html
from wattage.render.json_report import render_json
from wattage.render.junit import render_junit
from wattage.render.pr_comment import render_pr_comment
from wattage.render.sarif import render_sarif
from wattage.render.terminal import render_terminal
from wattage.report import build_report, build_trace_and_report
from wattage.scoring.quality import QualityMapError

app = typer.Typer(
    name="wattage",
    help="A token-spend profiler and cost-regression gate for AI agents.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"wattage {__version__}")
        raise typer.Exit()


_CONFIG_HELP = "Path to a wattage.yaml config file. Defaults to ./wattage.yaml if present."


def _load_config_or_exit(config_path: Path | None) -> WattageConfig:
    try:
        return load_config(str(config_path) if config_path else None)
    except WattageConfigError as exc:
        typer.echo(f"config error: {exc}", err=True)
        raise typer.Exit(code=2) from exc


_T = TypeVar("_T")


def _input_errors_or_exit(build: Callable[[], _T]) -> _T:
    """report/score/badge have no documented multi-code exit contract like
    `ci` does, so a bad --source/--pricing/--quality file just needs a
    clean message instead of `ci`'s carefully-scoped 0-4 codes -- a raw
    Python traceback for a missing or malformed file is not launch-quality
    UX, and `ci` already gets this right for the same underlying errors.
    """
    try:
        return build()
    except (
        OSError,
        json.JSONDecodeError,
        yaml.YAMLError,
        AdapterError,
        PricingConfigError,
        QualityMapError,
    ) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


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
    pricing: Annotated[Path | None, typer.Option(help="Path to a pricing.yaml override.")] = None,
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
    config: Annotated[Path | None, typer.Option("--config", help=_CONFIG_HELP)] = None,
) -> None:
    """Ingest a trace and print a priced, findings-quantified report."""
    cfg = _load_config_or_exit(config)
    if html_output is not None:
        trace, report_obj = _input_errors_or_exit(
            lambda: build_trace_and_report(
                str(source),
                pricing_override=str(pricing) if pricing else None,
                config=cfg,
                quality_file=str(quality) if quality else None,
            )
        )
        html_output.write_text(render_html(trace, report_obj), encoding="utf-8")
        typer.echo(f"wrote {html_output}")
        return
    report_obj = _input_errors_or_exit(
        lambda: build_report(
            str(source),
            pricing_override=str(pricing) if pricing else None,
            config=cfg,
            quality_file=str(quality) if quality else None,
        )
    )
    if json_output:
        typer.echo(render_json(report_obj))
    else:
        render_terminal(report_obj)


@app.command()
def score(
    source: Annotated[Path, typer.Argument(help="Path to an OTLP JSON trace file.")],
    pricing: Annotated[Path | None, typer.Option(help="Path to a pricing.yaml override.")] = None,
    quality: Annotated[
        Path | None,
        typer.Option(help="Path to a quality.json map; enables quality-gated findings."),
    ] = None,
    config: Annotated[Path | None, typer.Option("--config", help=_CONFIG_HELP)] = None,
) -> None:
    """Print just the Token Efficiency score and dollar headline."""
    cfg = _load_config_or_exit(config)
    report_obj = _input_errors_or_exit(
        lambda: build_report(
            str(source),
            pricing_override=str(pricing) if pricing else None,
            config=cfg,
            quality_file=str(quality) if quality else None,
        )
    )
    if report_obj.unpriced_calls:
        call_word = "call" if report_obj.unpriced_calls == 1 else "calls"
        models = ", ".join(report_obj.unpriced_models)
        typer.echo(
            f"unpriced ({report_obj.unpriced_calls} {call_word}: {models}) — "
            "see `wattage report` for detail"
        )
        return
    s = report_obj.score
    typer.echo(f"{s.grade} ({s.efficiency}) · {format_dollars(s.recoverable_dollars)} recoverable")


@app.command()
def badge(
    source: Annotated[Path, typer.Argument(help="Path to an OTLP JSON trace file.")],
    pricing: Annotated[Path | None, typer.Option(help="Path to a pricing.yaml override.")] = None,
    quality: Annotated[
        Path | None,
        typer.Option(help="Path to a quality.json map; enables quality-gated findings."),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", help="Write the SVG to this file instead of stdout.")
    ] = None,
    config: Annotated[Path | None, typer.Option("--config", help=_CONFIG_HELP)] = None,
) -> None:
    """Emit a Token Efficiency SVG badge."""
    cfg = _load_config_or_exit(config)
    report_obj = _input_errors_or_exit(
        lambda: build_report(
            str(source),
            pricing_override=str(pricing) if pricing else None,
            config=cfg,
            quality_file=str(quality) if quality else None,
        )
    )
    svg = render_badge(report_obj)
    if out is not None:
        out.write_text(svg, encoding="utf-8")
    else:
        typer.echo(svg)


@app.command()
def ci(
    source: Annotated[Path, typer.Argument(help="Path to an OTLP JSON trace file.")],
    baseline: Annotated[
        Path | None, typer.Option(help="Path to .wattage/baseline.json (default from config).")
    ] = None,
    pricing: Annotated[Path | None, typer.Option(help="Path to a pricing.yaml override.")] = None,
    quality: Annotated[
        Path | None,
        typer.Option(help="Path to a quality.json map; enables quality-gated findings."),
    ] = None,
    fail_on: Annotated[
        str | None,
        typer.Option(
            "--fail-on",
            help='e.g. "score_below:80,cost_delta_pct_above:5,any_critical:true".',
        ),
    ] = None,
    pr_comment_out: Annotated[
        Path | None, typer.Option("--pr-comment-out", help="Write the markdown PR comment here.")
    ] = None,
    sarif_out: Annotated[
        Path | None, typer.Option("--sarif-out", help="Write SARIF results here.")
    ] = None,
    junit_out: Annotated[
        Path | None, typer.Option("--junit-out", help="Write JUnit XML results here.")
    ] = None,
    badge_out: Annotated[
        Path | None, typer.Option("--badge-out", help="Write a Token Efficiency SVG badge here.")
    ] = None,
    config: Annotated[Path | None, typer.Option("--config", help=_CONFIG_HELP)] = None,
) -> None:
    """Cost-regression gate for CI: fails the build on a real regression."""
    cfg = _load_config_or_exit(config)
    try:
        parsed_fail_on = parse_fail_on(fail_on) if fail_on else None
    except CIConfigError as exc:
        typer.echo(f"config error: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    result = run_ci(
        str(source),
        baseline_path=str(baseline) if baseline else None,
        pricing_override=str(pricing) if pricing else None,
        quality_file=str(quality) if quality else None,
        fail_on=parsed_fail_on,
        config=cfg,
    )

    resolved_pr_comment_out = pr_comment_out or (
        Path(cfg.ci.pr_comment_out) if cfg.ci.pr_comment_out else None
    )
    resolved_sarif_out = sarif_out or (Path(cfg.ci.sarif_out) if cfg.ci.sarif_out else None)
    resolved_badge_out = badge_out or (Path(cfg.ci.badge_out) if cfg.ci.badge_out else None)

    if result.report is not None:
        render_terminal(result.report)
        if resolved_pr_comment_out is not None and result.baseline is not None:
            resolved_pr_comment_out.write_text(
                render_pr_comment(result.report, result.baseline), encoding="utf-8"
            )
        if resolved_sarif_out is not None:
            resolved_sarif_out.write_text(
                render_sarif(result.report, tool_version=__version__), encoding="utf-8"
            )
        if junit_out is not None:
            junit_out.write_text(
                render_junit(result.report, ci_reasons=result.reasons), encoding="utf-8"
            )
        if resolved_badge_out is not None:
            resolved_badge_out.write_text(render_badge(result.report), encoding="utf-8")

    for reason in result.reasons:
        typer.echo(f"- {reason}", err=result.exit_code != 0)

    raise typer.Exit(code=result.exit_code)


if __name__ == "__main__":
    app()
