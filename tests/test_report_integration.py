"""End-to-end pipeline test: ingest -> sessionize -> price -> detect -> score,
exercising three detectors together on one synthetic trace, to catch wiring
bugs (double-counted tokens, wrong aggregation) that isolated per-detector
unit tests wouldn't. Every expected number below is hand-derived from the
fixture's own token counts — see the comment beside each assertion.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wattage.report import build_report


def _attr(key: str, value: object) -> dict[str, object]:
    if isinstance(value, str):
        return {"key": key, "value": {"stringValue": value}}
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    raise TypeError(value)


def _chat(
    span_id: str, parent_id: str, input_tok: int, output_tok: int, start: int, end: int
) -> dict[str, object]:
    return {
        "traceId": "trace-INT",
        "spanId": span_id,
        "parentSpanId": parent_id,
        "name": "chat claude-sonnet-4-6",
        "startTimeUnixNano": str(start),
        "endTimeUnixNano": str(end),
        "attributes": [
            _attr("gen_ai.provider.name", "anthropic"),
            _attr("gen_ai.request.model", "claude-sonnet-4-6"),
            _attr("gen_ai.usage.input_tokens", input_tok),
            _attr("gen_ai.usage.output_tokens", output_tok),
            _attr("gen_ai.usage.cache_read_input_tokens", 0),
        ],
    }


def _tool(
    span_id: str, parent_id: str, name: str, query: str, result: str, start: int, end: int
) -> dict[str, object]:
    return {
        "traceId": "trace-INT",
        "spanId": span_id,
        "parentSpanId": parent_id,
        "name": f"execute_tool {name}",
        "startTimeUnixNano": str(start),
        "endTimeUnixNano": str(end),
        "attributes": [
            _attr("gen_ai.tool.name", name),
            {
                "key": "gen_ai.tool.call.arguments",
                "value": {"kvlistValue": {"values": [_attr("q", query)]}},
            },
            _attr("gen_ai.tool.call.result", result),
        ],
    }


def _agent(span_id: str, start: int, end: int) -> dict[str, object]:
    return {
        "traceId": "trace-INT",
        "spanId": span_id,
        "parentSpanId": None,
        "name": "invoke_agent support-bot",
        "startTimeUnixNano": str(start),
        "endTimeUnixNano": str(end),
        "attributes": [],
    }


@pytest.fixture
def integration_trace_path(tmp_path: Path) -> Path:
    tool_result = "policy text A" * 50  # 650 chars -> 162 estimated tokens (//4)
    spans = [
        _agent("agent-1", 0, 1000),
        # Iteration 0: no max_tokens + large output (verbosity), plus a tool call.
        _chat("chat-1", "agent-1", input_tok=15_000, output_tok=5_000, start=1, end=10),
        _tool("tool-1", "agent-1", "search_docs", "refund policy", tool_result, 10, 15),
        # Iteration 1: re-sends iteration 0's full context (prefix_churn) +
        # a duplicate tool call (redundant_tool_calls).
        _chat("chat-2", "agent-1", input_tok=20_500, output_tok=300, start=16, end=25),
        _tool("tool-2", "agent-1", "search_docs", "refund policy", tool_result, 25, 30),
        # Iteration 2: wraps up with a small, capped-looking output.
        _chat("chat-3", "agent-1", input_tok=21_200, output_tok=150, start=31, end=40),
    ]
    payload = {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}
    path = tmp_path / "integration_trace.json"
    path.write_text(json.dumps(payload))
    return path


def test_three_detectors_fire_and_aggregate_consistently(integration_trace_path: Path) -> None:
    report = build_report(str(integration_trace_path))

    by_id = {f.id: f for f in report.findings}
    assert set(by_id) == {"prefix_churn", "redundant_tool_calls", "verbosity"}

    # prefix_churn: chat-1's full context (15_000+5_000=20_000) re-sent into
    # chat-2 (input 20_500 >= 20_000); chat-2's context (20_500+300=20_800)
    # re-sent into chat-3 (input 21_200 >= 20_800). 20_000 + 20_800 = 40_800.
    assert by_id["prefix_churn"].wasted_tokens == 40_800
    assert by_id["prefix_churn"].wasted_dollars == pytest.approx(40_800 * 3.0e-6)

    # verbosity: only chat-1 has no max_tokens and output (5_000) over the
    # 1_000-token ceiling; excess = 4_000.
    assert by_id["verbosity"].wasted_tokens == 4_000
    assert by_id["verbosity"].wasted_dollars == pytest.approx(4_000 * 15.0e-6)

    # redundant_tool_calls: tool-2 duplicates tool-1 exactly (same args, same
    # result) -> 650-char result // 4 = 162 estimated tokens.
    assert by_id["redundant_tool_calls"].wasted_tokens == 162
    assert by_id["redundant_tool_calls"].wasted_dollars == pytest.approx(162 * 3.0e-6)

    # total_dollars: sum of the three chat calls' own input+output cost.
    expected_total = (
        (15_000 * 3.0e-6 + 5_000 * 15.0e-6)
        + (20_500 * 3.0e-6 + 300 * 15.0e-6)
        + (21_200 * 3.0e-6 + 150 * 15.0e-6)
    )
    assert report.total_dollars == pytest.approx(expected_total)

    # recoverable_dollars is the unfiltered sum of all three findings.
    expected_recoverable = (
        by_id["prefix_churn"].wasted_dollars
        + by_id["verbosity"].wasted_dollars
        + by_id["redundant_tool_calls"].wasted_dollars
    )
    assert report.score.recoverable_dollars == pytest.approx(expected_recoverable)

    # All three findings are quality_risk none/low, so waste_ratio counts all of them.
    assert report.score.waste_ratio == pytest.approx(expected_recoverable / expected_total)
    assert report.score.grade == "F"
