import io
import json
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


def test_report_json_flag_emits_valid_matching_json() -> None:
    result = runner.invoke(
        app, ["report", str(REPO_ROOT / "examples" / "sample_trace.json"), "--json"]
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["score"]["grade"] == "A"
    assert payload["token_breakdown"]["input"] == 18450


def test_report_html_flag_writes_a_self_contained_flame_graph(tmp_path: Path) -> None:
    out_path = tmp_path / "out.html"
    result = runner.invoke(
        app,
        ["report", str(REPO_ROOT / "examples" / "sample_trace.json"), "--html", str(out_path)],
    )
    assert result.exit_code == 0
    html = out_path.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    assert "<svg" in html


def test_score_command_prints_grade_and_headline() -> None:
    result = runner.invoke(app, ["score", str(REPO_ROOT / "examples" / "sample_trace.json")])
    assert result.exit_code == 0
    assert "A (100)" in result.stdout
    assert "recoverable" in result.stdout


def test_quality_flag_wires_a_real_quality_factor(tmp_path: Path) -> None:
    quality_file = tmp_path / "quality.json"
    quality_file.write_text(json.dumps({"tasks": {"t1": {"eval_score": 0.45}}}))

    without_quality = build_report(str(REPO_ROOT / "examples" / "sample_trace.json"))
    assert without_quality.score.quality_measured is False

    with_quality = build_report(
        str(REPO_ROOT / "examples" / "sample_trace.json"), quality_file=str(quality_file)
    )
    assert with_quality.score.quality_measured is True
    assert with_quality.score.quality_factor < 1.0


def test_badge_command_prints_svg_to_stdout() -> None:
    result = runner.invoke(app, ["badge", str(REPO_ROOT / "examples" / "sample_trace.json")])
    assert result.exit_code == 0
    assert result.stdout.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<svg" in result.stdout


def test_badge_command_writes_to_file(tmp_path: Path) -> None:
    out_path = tmp_path / "badge.svg"
    result = runner.invoke(
        app,
        [
            "badge",
            str(REPO_ROOT / "examples" / "sample_trace.json"),
            "--out",
            str(out_path),
        ],
    )
    assert result.exit_code == 0
    assert out_path.read_text(encoding="utf-8").startswith('<?xml version="1.0"')


def test_ci_command_exit_code_propagates_through_the_real_cli(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    passing = runner.invoke(
        app,
        [
            "ci",
            str(REPO_ROOT / "examples" / "sample_trace.json"),
            "--baseline",
            str(baseline_path),
        ],
    )
    assert passing.exit_code == 0

    failing = runner.invoke(
        app,
        [
            "ci",
            str(REPO_ROOT / "examples" / "sample_trace.json"),
            "--baseline",
            str(baseline_path),
            "--fail-on",
            "score_below:101",
        ],
    )
    assert failing.exit_code == 1


def test_ci_command_config_error_exit_code(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "ci",
            str(REPO_ROOT / "examples" / "sample_trace.json"),
            "--baseline",
            str(tmp_path / "baseline.json"),
            "--fail-on",
            "garbage-not-a-clause",
        ],
    )
    assert result.exit_code == 2


def test_ci_command_writes_pr_comment_sarif_and_junit_outputs(tmp_path: Path) -> None:
    pr_comment_path = tmp_path / "pr_comment.md"
    sarif_path = tmp_path / "wattage.sarif"
    junit_path = tmp_path / "junit.xml"
    badge_path = tmp_path / "badge.svg"

    result = runner.invoke(
        app,
        [
            "ci",
            str(REPO_ROOT / "benchmarks" / "traces" / "any_agent_openai.otlp.json"),
            "--baseline",
            str(tmp_path / "baseline.json"),
            "--fail-on",
            "score_below:0,any_critical:false",
            "--pr-comment-out",
            str(pr_comment_path),
            "--sarif-out",
            str(sarif_path),
            "--junit-out",
            str(junit_path),
            "--badge-out",
            str(badge_path),
        ],
    )

    assert result.exit_code == 0
    assert "no baseline yet" in pr_comment_path.read_text(encoding="utf-8")
    assert json.loads(sarif_path.read_text(encoding="utf-8"))["version"] == "2.1.0"
    assert junit_path.read_text(encoding="utf-8").startswith('<?xml version="1.0"')
    assert badge_path.read_text(encoding="utf-8").startswith('<?xml version="1.0"')
