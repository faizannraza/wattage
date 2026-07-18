import io
from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

from wattage.cli import app
from wattage.render.terminal import render_terminal
from wattage.report import build_report

REPO_ROOT = Path(__file__).parent.parent
runner = CliRunner()


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "wattage" in result.stdout


def test_report_command_runs_against_example_fixture() -> None:
    result = runner.invoke(app, ["report", str(REPO_ROOT / "examples" / "sample_trace.json")])
    assert result.exit_code == 0
    assert "Total cost" in result.stdout


def test_report_output_matches_golden_fixture() -> None:
    # The golden fixture bakes in "examples/sample_trace.json" as trace_source,
    # so this must be invoked with that same relative path (cwd == repo root
    # when tests run), not an absolute one.
    report = build_report("examples/sample_trace.json")

    buf = io.StringIO()
    console = Console(file=buf, width=100, no_color=True, force_terminal=False)
    render_terminal(report, console=console)

    golden = (REPO_ROOT / "examples" / "sample_report.golden.txt").read_text()
    assert buf.getvalue() == golden


def test_report_prices_example_fixture_correctly() -> None:
    report = build_report(str(REPO_ROOT / "examples" / "sample_trace.json"))
    assert report.token_breakdown == {
        "input": 18450,
        "output": 320,
        "cache_read": 0,
        "cache_creation": 0,
        "reasoning": 0,
    }
    expected_total = 18450 * 3.0e-6 + 320 * 15.0e-6
    assert abs(report.total_dollars - expected_total) < 1e-9
