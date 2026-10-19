"""tool_result_bloat detector tests: oversized tool results dumped into the
context.

The dollar figure is a deliberate chars/4 UNDER-estimate priced once at the
task's input rate, capped at the task's actual billed dollars, with basis
`estimated` — a projection that can never fail a CI build or claim more
waste than the task cost in the first place.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from wattage.config import WattageConfig
from wattage.detectors.base import AnalysisContext
from wattage.detectors.tool_result_bloat import ToolResultBloatDetector
from wattage.models import (
    Finding,
    FindingBasis,
    Iteration,
    LLMCall,
    Loop,
    Session,
    Severity,
    Task,
    TokenUsage,
    ToolCall,
)
from wattage.pricing.engine import PricingEngine
from wattage.pricing.registry import PricingRegistry

# Defaults from ToolResultBloatConfig, restated here so a silent config
# change shows up as a test failure rather than a silently moved threshold.
_CEILING = 20_000
_HIGH_MULTIPLIER = 4.0


def _llm(engine: PricingEngine, span_id: str, start: int = 0) -> LLMCall:
    call = LLMCall(
        span_id=span_id,
        provider="anthropic",
        model="claude-sonnet-4-6",
        usage=TokenUsage(input=100, output=10),
        start_ns=start,
    )
    call.cost = engine.price_call(call)
    return call


def _tool(span_id: str, result: str, name: str = "Read", start: int = 0) -> ToolCall:
    return ToolCall(span_id=span_id, name=name, result=result, start_ns=start)


def _analyze(
    engine: PricingEngine, llm_calls: list[LLMCall], tool_calls: list[ToolCall]
) -> list[Finding]:
    iteration = Iteration(index=0, llm_calls=llm_calls, tool_calls=tool_calls)
    task = Task(task_id="t0", loops=[Loop(loop_id="t0:loop0", iterations=[iteration])])
    session = Session(session_id="s0", tasks=[task])
    ctx = AnalysisContext(pricing=engine, config=WattageConfig())
    return ToolResultBloatDetector().analyze(session, ctx)


def test_oversized_result_dollars_are_capped_at_task_billed_total() -> None:
    """The chars/4 projection must never claim more waste than the task
    actually cost: a 30,000-char result's excess (10,000 chars -> 2,500
    tokens at the input rate) exceeds this tiny task's whole bill, so the
    reported dollars must be exactly the task's billed total, not the
    larger estimate."""
    engine = PricingEngine(PricingRegistry.load())
    llm = _llm(engine, "l1")
    findings = _analyze(engine, [llm], [_tool("t1", "x" * 30_000)])

    assert len(findings) == 1
    finding = findings[0]
    assert finding.basis == FindingBasis.estimated
    excess_tokens = (30_000 - _CEILING) // 4
    assert finding.wasted_tokens == excess_tokens
    input_rate = engine.registry.get("anthropic", "claude-sonnet-4-6").input
    assert excess_tokens * input_rate > llm.cost.total  # the cap is actually load-bearing
    assert finding.wasted_dollars == llm.cost.total


def test_results_under_the_ceiling_produce_no_findings() -> None:
    engine = PricingEngine(PricingRegistry.load())
    findings = _analyze(engine, [_llm(engine, "l1")], [_tool("t1", "x" * (_CEILING - 1))])
    assert findings == []


def test_two_oversized_calls_of_the_same_tool_aggregate_into_one_finding() -> None:
    """One oversized tool is one problem with one fix (truncate at the tool
    boundary) — two offending calls must aggregate into a single finding
    carrying both span_ids, not spam one finding per call."""
    engine = PricingEngine(PricingRegistry.load())
    findings = _analyze(
        engine,
        [_llm(engine, "l1")],
        [_tool("t1", "x" * 25_000, start=10), _tool("t2", "y" * 30_000, start=20)],
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.span_ids == ["t1", "t2"]
    assert finding.wasted_tokens == ((25_000 - _CEILING) + (30_000 - _CEILING)) // 4
    assert finding.severity == Severity.medium  # worst (30,000) is under the 4x bar


def test_worst_result_at_four_times_the_ceiling_is_high_severity() -> None:
    engine = PricingEngine(PricingRegistry.load())
    result_len = int(_CEILING * _HIGH_MULTIPLIER)  # exactly the >= boundary
    findings = _analyze(engine, [_llm(engine, "l1")], [_tool("t1", "x" * result_len)])

    assert len(findings) == 1
    assert findings[0].severity == Severity.high


def test_result_exactly_at_the_ceiling_is_not_flagged() -> None:
    """The ceiling is a strict bound: a result of exactly result_char_ceiling
    chars is within policy, and flagging it would make the configured limit
    a lie by one character."""
    engine = PricingEngine(PricingRegistry.load())
    findings = _analyze(engine, [_llm(engine, "l1")], [_tool("t1", "x" * _CEILING)])
    assert findings == []


# A model priced through dated rate windows -- the shape of Google's promo
# pricing (gemini-3.7-flash: promo rates through 2026-12-31, higher rates
# from 2027-01-01) in the vendored pricing snapshot. The cheap window is
# dated in the past and the expensive one has no end date, so the window
# covering "now" is always the expensive one -- which is exactly how a
# trace recorded during the cheap window gets mispriced.
_WINDOWED_PRICING = """
version: "test-windowed"
providers:
  google:
    test-windowed-model:
      rates:
        - from: "2000-01-01"
          until: "2000-12-31"
          input: 1.0e-6
          output: 2.0e-6
        - from: "2001-01-01"
          input: 9.0e-6
          output: 9.0e-6
"""

_CHEAP_WINDOW_RATE = 1.0e-6
_EXPENSIVE_WINDOW_RATE = 9.0e-6


def test_waste_is_priced_at_the_rate_window_the_call_was_billed_under(
    tmp_path: Path,
) -> None:
    """The waste figure must be priced at the rate the call was ACTUALLY
    billed at, not at whichever rate window covers the day the analysis
    happens to run.

    Every other detector resolves its rate card through rate_card_for(),
    which pins the window to the call's own timestamp ("a trace from a
    promo-pricing period must not have its waste priced at the post-promo
    rate" -- detectors/base.py). This detector resolved a bare
    registry.get() instead, so a call made during a cheap dated window was
    priced at the current (expensive) window's rate, inflating the reported
    waste by the ratio between the two windows.
    """
    pricing_path = tmp_path / "pricing.yaml"
    pricing_path.write_text(_WINDOWED_PRICING, encoding="utf-8")
    registry = PricingRegistry.load(path=pricing_path)
    engine = PricingEngine(registry)

    # A call that ran inside the FIRST (cheap) window.
    call_ns = int(datetime(2000, 6, 15, tzinfo=timezone.utc).timestamp() * 1_000_000_000)
    call = LLMCall(
        span_id="l1",
        provider="google",
        model="test-windowed-model",
        usage=TokenUsage(input=1_000_000),
        start_ns=call_ns,
        end_ns=call_ns,
    )
    call.cost = engine.price_call(call)
    # The engine prices the call at its own timestamp, so the task's real
    # bill is at the cheap rate -- and large enough that the "capped at the
    # task's billed total" rule is not what is under test here.
    assert call.cost.total == pytest.approx(1_000_000 * _CHEAP_WINDOW_RATE)

    result_len = 100_000
    findings = _analyze(engine, [call], [_tool("t1", "x" * result_len)])

    assert len(findings) == 1
    finding = findings[0]
    excess_tokens = (result_len - _CEILING) // 4
    assert finding.wasted_tokens == excess_tokens
    # The rate that was actually in effect when the call ran -- not the
    # current window's rate, which is 9x higher.
    assert finding.wasted_dollars == pytest.approx(excess_tokens * _CHEAP_WINDOW_RATE)
    assert finding.wasted_dollars != pytest.approx(excess_tokens * _EXPENSIVE_WINDOW_RATE)
