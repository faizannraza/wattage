"""Formalizes the CI exit-code behavior manually verified against real
fixtures during development (doc plan 4.2/4.10): 0 pass, 1 fail (score and
cost-regression paths, verified independently), 2 config error, 3 ingestion
error (missing file, malformed JSON, empty trace), 4 pricing error.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wattage.ci import (
    EXIT_CONFIG_ERROR,
    EXIT_FAIL,
    EXIT_INGESTION_ERROR,
    EXIT_PASS,
    EXIT_PRICING_ERROR,
    CIConfigError,
    parse_fail_on,
    run_ci,
)

REPO_ROOT = Path(__file__).parent.parent
SAMPLE_TRACE = REPO_ROOT / "examples" / "sample_trace.json"
REAL_TRACE = REPO_ROOT / "benchmarks" / "traces" / "any_agent_openai.otlp.json"


def test_parse_fail_on_matches_the_docs_action_yml_example() -> None:
    parsed = parse_fail_on("score_below:80,cost_delta_pct_above:5,any_critical:true")
    assert parsed.score_below == 80
    assert parsed.cost_delta_pct_above == 5.0
    assert parsed.any_critical is True


def test_parse_fail_on_rejects_malformed_clauses() -> None:
    with pytest.raises(CIConfigError):
        parse_fail_on("not-a-valid-clause")


def test_parse_fail_on_rejects_non_numeric_values() -> None:
    with pytest.raises(CIConfigError):
        parse_fail_on("score_below:not-a-number")


def test_first_run_with_no_baseline_passes_and_creates_one(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    result = run_ci(str(SAMPLE_TRACE), baseline_path=str(baseline_path))

    assert result.exit_code == EXIT_PASS
    assert baseline_path.exists()
    saved = json.loads(baseline_path.read_text())
    assert saved["last_passing"]["grade"] == "A"


def test_result_baseline_is_the_pre_run_state_not_the_just_updated_one(tmp_path: Path) -> None:
    """A real bug caught by hand: CIResult.baseline must reflect what this
    run was compared *against*, not the baseline after this run updated it —
    otherwise a PR comment diffing against it always shows "no change",
    since a passing run would be diffed against itself."""
    baseline_path = tmp_path / "baseline.json"
    result = run_ci(str(REAL_TRACE), baseline_path=str(baseline_path))

    assert result.baseline is not None
    assert result.baseline.last_passing is None  # nothing existed before this run


def test_score_below_threshold_fails_with_a_clear_reason(tmp_path: Path) -> None:
    result = run_ci(
        str(SAMPLE_TRACE),
        baseline_path=str(tmp_path / "baseline.json"),
        fail_on=parse_fail_on("score_below:101"),
    )
    assert result.exit_code == EXIT_FAIL
    assert any("below threshold 101" in r for r in result.reasons)


def test_cost_regression_fails_independent_of_score(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    lenient = parse_fail_on("score_below:0,any_critical:false")

    first = run_ci(str(REAL_TRACE), baseline_path=str(baseline_path), fail_on=lenient)
    assert first.exit_code == EXIT_PASS  # establishes last_passing

    inflated_pricing = tmp_path / "inflated.yaml"
    inflated_pricing.write_text(
        "version: 'inflated-test'\n"
        "providers:\n"
        "  mistral:\n"
        "    mistral-small-latest:\n"
        "      input: 1.5e-6\n"
        "      output: 6.0e-6\n"
        "      cache_read_mult: 0.10\n"
    )
    regression_fail_on = parse_fail_on("score_below:0,any_critical:false,cost_delta_pct_above:5")
    second = run_ci(
        str(REAL_TRACE),
        baseline_path=str(baseline_path),
        pricing_override=str(inflated_pricing),
        fail_on=regression_fail_on,
    )
    assert second.exit_code == EXIT_FAIL
    assert any("cost increased" in r for r in second.reasons)


def test_failed_run_does_not_corrupt_the_baseline(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    passing = run_ci(
        str(SAMPLE_TRACE), baseline_path=str(baseline_path), fail_on=parse_fail_on("score_below:0")
    )
    assert passing.exit_code == EXIT_PASS

    run_ci(
        str(SAMPLE_TRACE),
        baseline_path=str(baseline_path),
        fail_on=parse_fail_on("score_below:101"),
    )

    saved = json.loads(baseline_path.read_text())
    assert saved["last_passing"]["efficiency"] == 100  # untouched by the failing run


@pytest.mark.parametrize(
    "make_source",
    [
        lambda tmp_path: str(tmp_path / "does-not-exist.json"),
        lambda tmp_path: _write(tmp_path / "bad.json", "not json"),
        lambda tmp_path: _write(tmp_path / "empty.json", json.dumps({"resourceSpans": []})),
    ],
    ids=["missing-file", "malformed-json", "empty-trace"],
)
def test_ingestion_errors_return_exit_code_3(tmp_path: Path, make_source: object) -> None:
    source = make_source(tmp_path)  # type: ignore[operator]
    result = run_ci(source, baseline_path=str(tmp_path / "baseline.json"))
    assert result.exit_code == EXIT_INGESTION_ERROR


def _write(path: Path, content: str) -> str:
    path.write_text(content)
    return str(path)


def test_unpriced_model_returns_exit_code_4(tmp_path: Path) -> None:
    trace_path = tmp_path / "unknown_model.json"
    trace_path.write_text(
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
                                                "value": {"stringValue": "mystery-corp"},
                                            },
                                            {
                                                "key": "gen_ai.request.model",
                                                "value": {"stringValue": "ghost-model-9000"},
                                            },
                                            {
                                                "key": "gen_ai.usage.input_tokens",
                                                "value": {"intValue": "100"},
                                            },
                                            {
                                                "key": "gen_ai.usage.output_tokens",
                                                "value": {"intValue": "10"},
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
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = run_ci(str(trace_path), baseline_path=str(tmp_path / "baseline.json"))
    assert result.exit_code == EXIT_PRICING_ERROR
    assert any("no pricing entry" in r for r in result.reasons)


def test_exit_code_constants_match_the_doc_table() -> None:
    assert (EXIT_PASS, EXIT_FAIL, EXIT_CONFIG_ERROR, EXIT_INGESTION_ERROR, EXIT_PRICING_ERROR) == (
        0,
        1,
        2,
        3,
        4,
    )
