"""Phase 1's real-trace validation gate (doc plan 1.10), pinned as a regression
test. See benchmarks/traces/README.md for full provenance: this is a genuine
trace from mozilla-ai/any-agent's own integration test suite (Apache-2.0),
converted to OTLP wire format with no change to its substance.

Every expected number here is hand-derived from the trace's own token counts
(see the comment beside each assertion) — nothing is asserted "because that's
what the code currently outputs."
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wattage.report import build_report

TRACE_PATH = (
    Path(__file__).parent.parent / "benchmarks" / "traces" / "any_agent_openai.otlp.json"
)


def test_real_trace_prices_correctly_and_finds_exactly_the_expected_waste() -> None:
    report = build_report(str(TRACE_PATH))

    # Three real LLM calls: (input=269, output=16), (359, 14), (392, 46).
    assert report.token_breakdown["input"] == 269 + 359 + 392
    assert report.token_breakdown["output"] == 16 + 14 + 46
    expected_total = (269 + 359 + 392) * 0.15e-6 + (16 + 14 + 46) * 0.6e-6
    assert report.total_dollars == pytest.approx(expected_total)

    # Exactly one finding: prefix_churn. The other three detectors correctly
    # stay silent (different tool names -> no redundant_tool_calls; no
    # max_tokens but small outputs -> no verbosity; no cache usage at all
    # in this trace -> no cache_gap, since caching was never attempted).
    assert [f.id for f in report.findings] == ["prefix_churn"]

    finding = report.findings[0]
    # call1's context (269+16=285) re-sent into call2 (input 359 >= 285);
    # call2's context (359+14=373) re-sent into call3 (input 392 >= 373).
    assert finding.wasted_tokens == 285 + 373
    assert finding.wasted_dollars == pytest.approx((285 + 373) * 0.15e-6)
    assert finding.severity.value == "high"

    assert report.score.grade == "F"
    assert report.score.efficiency == round(100 * (1 - finding.wasted_dollars / expected_total))
