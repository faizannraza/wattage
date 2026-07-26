import io
import json
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from wattage import __version__
from wattage.cli import app
from wattage.render.terminal import render_terminal
from wattage.report import build_report

REPO_ROOT = Path(__file__).parent.parent
runner = CliRunner()


def _write_unpriced_trace(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "resourceSpans": [
                    {
                        "scopeSpans": [
                            {
                                "spans": [
                                    {
                                        "traceId": "t1",
                                        "spanId": "s1",
                                        "parentSpanId": "",
                                        "name": "chat",
                                        "startTimeUnixNano": "0",
                                        "endTimeUnixNano": "1",
                                        "attributes": [
                                            {
                                                "key": "gen_ai.provider.name",
                                                "value": {"stringValue": "openai"},
                                            },
                                            {
                                                "key": "gen_ai.request.model",
                                                "value": {"stringValue": "gpt-4o"},
                                            },
                                            {
                                                "key": "gen_ai.usage.input_tokens",
                                                "value": {"intValue": "5000"},
                                            },
                                            {
                                                "key": "gen_ai.usage.output_tokens",
                                                "value": {"intValue": "2000"},
                                            },
                                        ],
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        )
    )


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


def test_default_console_is_pinned_to_a_fixed_width_not_the_live_terminal(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """render_terminal's default (no console passed -- the real path every
    CLI invocation actually takes) must render at a fixed width regardless
    of the ambient terminal, or the exact same report looks different for
    every user/environment, contradicting the "share this, docs show
    exactly this" premise the report is built around."""
    report = build_report("examples/sample_trace.json")

    render_terminal(report)

    out = capsys.readouterr().out
    border_line = next(line for line in out.splitlines() if line.startswith("╭"))
    golden_border = next(
        line
        for line in (REPO_ROOT / "examples" / "sample_report.golden.txt").read_text().splitlines()
        if line.startswith("╭")
    )
    assert len(border_line) == len(golden_border)


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


def test_score_command_shows_unpriced_not_a_fake_grade(tmp_path: Path) -> None:
    """A grade computed from an incomplete cost figure (an unknown model)
    must never print as a normal-looking "A (100)" -- that's exactly the
    plausible-looking-but-wrong number this project exists to avoid."""
    trace_path = tmp_path / "unpriced.json"
    _write_unpriced_trace(trace_path)

    result = runner.invoke(app, ["score", str(trace_path)])

    assert result.exit_code == 0
    assert "unpriced" in result.stdout
    assert "openai/gpt-4o" in result.stdout
    assert "A (100)" not in result.stdout


def test_report_command_shows_unpriced_warning_prominently(tmp_path: Path) -> None:
    trace_path = tmp_path / "unpriced.json"
    _write_unpriced_trace(trace_path)

    result = runner.invoke(app, ["report", str(trace_path)])

    assert result.exit_code == 0
    assert "unpriced" in result.stdout
    assert "openai/gpt-4o" in result.stdout
    assert "incomplete" in result.stdout
    assert "not a" in result.stdout and "confirmed-efficient" in result.stdout


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


def test_config_flag_actually_changes_detector_behavior(tmp_path: Path) -> None:
    """The real bug this closes: wattage.yaml had a full pydantic schema and
    was described in config.py's own docstring and CONTRIBUTING.md, but no
    code path anywhere ever loaded one -- every command silently used bare
    defaults. This must change what the CLI actually reports, not just
    parse without error."""
    scenario = REPO_ROOT / "benchmarks" / "scenarios" / "scenario1.json"
    without_config = runner.invoke(app, ["report", str(scenario), "--json"])
    assert without_config.exit_code == 0
    ids_without = {f["id"] for f in json.loads(without_config.stdout)["findings"]}
    assert "redundant_tool_calls" in ids_without  # confirmed present in the base case

    config_path = tmp_path / "wattage.yaml"
    config_path.write_text("detectors:\n  redundant_tool_calls:\n    enabled: false\n")
    with_config = runner.invoke(
        app, ["report", str(scenario), "--json", "--config", str(config_path)]
    )
    assert with_config.exit_code == 0
    ids_with = {f["id"] for f in json.loads(with_config.stdout)["findings"]}
    assert "redundant_tool_calls" not in ids_with
    assert ids_with == ids_without - {"redundant_tool_calls"}


def test_ci_command_reads_fail_on_thresholds_from_config_file(tmp_path: Path) -> None:
    """run_ci falls back to config.ci.fail_on when --fail-on isn't passed --
    a different code path from build_report's config wiring, so this needs
    its own real end-to-end check, not just an inference from the report/
    score/badge tests passing."""
    without_config = runner.invoke(
        app,
        [
            "ci",
            str(REPO_ROOT / "examples" / "sample_trace.json"),
            "--baseline",
            str(tmp_path / "baseline_a.json"),
        ],
    )
    assert without_config.exit_code == 0  # passes on the default score_below:80

    # sample_trace.json scores a perfect efficiency=100 -- no real
    # score_below value could ever fail it, so 101 is deliberately
    # impossible-to-satisfy, chosen only to prove this exact value came
    # from the config file (not passed via --fail-on) and was actually
    # read, not to represent a realistic threshold.
    config_path = tmp_path / "wattage.yaml"
    config_path.write_text("ci:\n  fail_on:\n    score_below: 101\n    any_critical: false\n")
    with_config = runner.invoke(
        app,
        [
            "ci",
            str(REPO_ROOT / "examples" / "sample_trace.json"),
            "--baseline",
            str(tmp_path / "baseline_b.json"),
            "--config",
            str(config_path),
        ],
    )

    # exit_code 1 (vs. 0 above, on the exact same trace and no other change)
    # is the load-bearing proof the config file's threshold was read.
    assert with_config.exit_code == 1


def test_ci_command_reads_output_paths_from_config_file(tmp_path: Path) -> None:
    """badge_out/sarif_out/pr_comment_out (doc §9.6) must actually be
    consumed as fallbacks when the matching --*-out flag isn't passed --
    these three config fields existed in the schema but were silently
    ignored by the ci command until now."""
    config_path = tmp_path / "wattage.yaml"
    badge_path = tmp_path / "badge.svg"
    sarif_path = tmp_path / "wattage.sarif"
    pr_comment_path = tmp_path / "pr_comment.md"
    config_path.write_text(
        "ci:\n"
        f"  badge_out: {badge_path}\n"
        f"  sarif_out: {sarif_path}\n"
        f"  pr_comment_out: {pr_comment_path}\n"
    )

    result = runner.invoke(
        app,
        [
            "ci",
            str(REPO_ROOT / "benchmarks" / "traces" / "any_agent_openai.otlp.json"),
            "--baseline",
            str(tmp_path / "baseline.json"),
            "--fail-on",
            "score_below:0,any_critical:false",
            "--config",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    assert badge_path.read_text(encoding="utf-8").startswith('<?xml version="1.0"')
    assert json.loads(sarif_path.read_text(encoding="utf-8"))["version"] == "2.1.0"
    assert "no baseline yet" in pr_comment_path.read_text(encoding="utf-8")


def test_ci_command_explicit_flag_overrides_config_output_path(tmp_path: Path) -> None:
    config_path = tmp_path / "wattage.yaml"
    config_badge_path = tmp_path / "config_badge.svg"
    flag_badge_path = tmp_path / "flag_badge.svg"
    config_path.write_text(f"ci:\n  badge_out: {config_badge_path}\n")

    result = runner.invoke(
        app,
        [
            "ci",
            str(REPO_ROOT / "examples" / "sample_trace.json"),
            "--baseline",
            str(tmp_path / "baseline.json"),
            "--config",
            str(config_path),
            "--badge-out",
            str(flag_badge_path),
        ],
    )

    assert result.exit_code == 0
    assert flag_badge_path.exists()
    assert not config_badge_path.exists()


def test_config_flag_missing_file_is_a_clean_exit_code_2(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "report",
            str(REPO_ROOT / "examples" / "sample_trace.json"),
            "--config",
            str(tmp_path / "does_not_exist.yaml"),
        ],
    )
    assert result.exit_code == 2


@pytest.mark.parametrize("command", ["report", "score", "badge"])
def test_missing_source_file_is_a_clean_error_not_a_traceback(command: str, tmp_path: Path) -> None:
    """The real bug this closes: report/score/badge didn't catch anything
    around ingestion, unlike `ci`, so a missing or malformed --source/
    --pricing/--quality file dumped a full Python traceback instead of a
    one-line message and a clean nonzero exit code."""
    result = runner.invoke(app, [command, str(tmp_path / "does_not_exist.json")])

    assert result.exit_code == 1
    assert result.exception is not None
    assert not isinstance(result.exception, FileNotFoundError)


@pytest.mark.parametrize("command", ["report", "score", "badge"])
def test_empty_trace_is_a_clean_error_not_a_confident_fake_grade(
    command: str, tmp_path: Path
) -> None:
    """A trace with zero sessions used to render a perfectly normal-looking
    "A (100)"/"this trace looks efficient" -- exactly the kind of
    plausible-but-vacuous number this project exists to avoid. Must now be
    a clean error, matching how `ci` already treats an empty trace."""
    empty_path = tmp_path / "empty.json"
    empty_path.write_text(json.dumps({"resourceSpans": []}))

    result = runner.invoke(app, [command, str(empty_path)])

    assert result.exit_code == 1
    assert "A (100)" not in result.stdout


def test_malformed_trace_via_report_is_a_clean_error_not_a_traceback(tmp_path: Path) -> None:
    trace_path = tmp_path / "missing_span_id.json"
    trace_path.write_text(
        json.dumps(
            {"resourceSpans": [{"scopeSpans": [{"spans": [{"traceId": "t1", "name": "chat"}]}]}]}
        )
    )

    result = runner.invoke(app, ["report", str(trace_path)])

    assert result.exit_code == 1
    assert not isinstance(result.exception, KeyError)


def test_malformed_pricing_override_via_report_is_a_clean_error_not_a_traceback(
    tmp_path: Path,
) -> None:
    bad_pricing = tmp_path / "bad_pricing.yaml"
    bad_pricing.write_text("not: valid: yaml: [")

    result = runner.invoke(
        app,
        [
            "report",
            str(REPO_ROOT / "examples" / "sample_trace.json"),
            "--pricing",
            str(bad_pricing),
        ],
    )

    assert result.exit_code == 1


def test_malformed_quality_map_via_score_is_a_clean_error_not_a_traceback(tmp_path: Path) -> None:
    bad_quality = tmp_path / "bad_quality.json"
    bad_quality.write_text("not json")

    result = runner.invoke(
        app,
        [
            "score",
            str(REPO_ROOT / "examples" / "sample_trace.json"),
            "--quality",
            str(bad_quality),
        ],
    )

    assert result.exit_code == 1


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


def test_ci_command_malformed_trace_is_a_clean_exit_code_3_not_an_uncaught_crash(
    tmp_path: Path,
) -> None:
    """A span missing 'spanId' used to blow up run_ci with a bare KeyError,
    which typer/Click renders as an uncaught-exception traceback and Python's
    default exit code 1 -- indistinguishable, at the CLI boundary, from a
    real cost regression (also exit code 1). Must be a clean exit code 3."""
    trace_path = tmp_path / "missing_span_id.json"
    trace_path.write_text(
        json.dumps(
            {"resourceSpans": [{"scopeSpans": [{"spans": [{"traceId": "t1", "name": "chat"}]}]}]}
        )
    )

    result = runner.invoke(
        app,
        ["ci", str(trace_path), "--baseline", str(tmp_path / "baseline.json")],
    )

    assert result.exit_code == 3
    assert not isinstance(result.exception, KeyError)


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
    sarif = json.loads(sarif_path.read_text(encoding="utf-8"))
    assert sarif["version"] == "2.1.0"
    assert sarif["runs"][0]["tool"]["driver"]["version"] == __version__
    assert junit_path.read_text(encoding="utf-8").startswith('<?xml version="1.0"')
    assert badge_path.read_text(encoding="utf-8").startswith('<?xml version="1.0"')
