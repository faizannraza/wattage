from hypothesis import given
from hypothesis import strategies as st

from wattage.config import WattageConfig
from wattage.detectors.base import AnalysisContext
from wattage.detectors.verbosity import VerbosityDetector
from wattage.models import Finding, LLMCall, Session, Task, TokenUsage
from wattage.pricing.engine import PricingEngine
from wattage.pricing.registry import PricingRegistry

_OUTPUT_RATE = 15.0e-6  # claude-sonnet-4-6


def _call(
    engine: PricingEngine, span_id: str, output: int, max_tokens: int | None = None
) -> LLMCall:
    call = LLMCall(
        span_id=span_id,
        provider="anthropic",
        model="claude-sonnet-4-6",
        usage=TokenUsage(input=500, output=output),
        max_tokens=max_tokens,
        start_ns=0,
    )
    call.cost = engine.price_call(call)
    return call


def _run(engine: PricingEngine, call: LLMCall) -> list[Finding]:
    task = Task(task_id="t", llm_calls=[call])
    session = Session(session_id="s", tasks=[task])
    ctx = AnalysisContext(pricing=engine, config=WattageConfig())
    return VerbosityDetector().analyze(session, ctx)


def test_capped_call_never_flagged_regardless_of_output_size() -> None:
    engine = PricingEngine(PricingRegistry.load())
    findings = _run(engine, _call(engine, "a", output=50_000, max_tokens=60_000))
    assert findings == []


def test_output_under_ceiling_not_flagged() -> None:
    engine = PricingEngine(PricingRegistry.load())
    findings = _run(engine, _call(engine, "b", output=500))
    assert findings == []


def test_output_over_ceiling_yields_exact_excess_and_medium_severity() -> None:
    engine = PricingEngine(PricingRegistry.load())
    findings = _run(engine, _call(engine, "c", output=1500))
    assert len(findings) == 1
    finding = findings[0]
    assert finding.wasted_tokens == 500  # 1500 - 1000 ceiling
    assert finding.wasted_dollars == 500 * _OUTPUT_RATE
    assert finding.severity.value == "medium"


def test_output_far_over_ceiling_yields_high_severity() -> None:
    engine = PricingEngine(PricingRegistry.load())
    findings = _run(engine, _call(engine, "d", output=5000))
    assert len(findings) == 1
    assert findings[0].severity.value == "high"
    assert findings[0].wasted_tokens == 4000


@given(output=st.integers(min_value=0, max_value=1_000_000), max_tokens=st.integers(min_value=1))
def test_property_a_set_max_tokens_always_suppresses_the_finding(
    output: int, max_tokens: int
) -> None:
    engine = PricingEngine(PricingRegistry.load())
    findings = _run(engine, _call(engine, "e", output=output, max_tokens=max_tokens))
    assert findings == []


@given(output=st.integers(min_value=0, max_value=1000))
def test_property_never_flags_at_or_under_the_ceiling(output: int) -> None:
    engine = PricingEngine(PricingRegistry.load())
    findings = _run(engine, _call(engine, "f", output=output))
    assert findings == []
