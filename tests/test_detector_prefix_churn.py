from hypothesis import given
from hypothesis import strategies as st

from wattage.config import WattageConfig
from wattage.detectors.base import AnalysisContext
from wattage.detectors.prefix_churn import PrefixChurnDetector
from wattage.models import LLMCall, Session, Task, TokenUsage
from wattage.pricing.engine import PricingEngine
from wattage.pricing.registry import PricingRegistry


def _priced_call(
    engine: PricingEngine,
    span_id: str,
    input_tok: int,
    output_tok: int,
    cache_read: int = 0,
    start: int = 0,
    model: str = "claude-sonnet-4-6",
) -> LLMCall:
    call = LLMCall(
        span_id=span_id,
        provider="anthropic",
        model=model,
        usage=TokenUsage(input=input_tok, output=output_tok, cache_read=cache_read),
        start_ns=start,
    )
    call.cost = engine.price_call(call)
    return call


def _ctx(engine: PricingEngine) -> AnalysisContext:
    return AnalysisContext(pricing=engine, config=WattageConfig())


def test_exact_known_resent_prefix_yields_exact_wasted_tokens() -> None:
    """Golden case (plan 1.9): a 12k-token re-sent prefix with cache_read=0
    must yield exactly that many wasted tokens."""
    engine = PricingEngine(PricingRegistry.load())
    call_a = _priced_call(engine, "a", input_tok=12_000, output_tok=300, start=0)
    call_b = _priced_call(engine, "b", input_tok=12_500, output_tok=280, start=1)
    task = Task(task_id="t0", llm_calls=[call_a, call_b])
    session = Session(session_id="s0", tasks=[task])

    findings = PrefixChurnDetector().analyze(session, _ctx(engine))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.id == "prefix_churn"
    assert finding.wasted_tokens == 12_300  # 12_000 input + 300 output from call_a
    assert finding.wasted_dollars == 12_300 * 3.0e-6  # claude-sonnet-4-6 input rate
    assert finding.span_ids == ["b"]


def test_guard_never_flags_when_cache_read_present() -> None:
    engine = PricingEngine(PricingRegistry.load())
    call_a = _priced_call(engine, "a", input_tok=12_000, output_tok=300, start=0)
    call_b = _priced_call(engine, "b", input_tok=12_500, output_tok=280, cache_read=12_000, start=1)
    task = Task(task_id="t0", llm_calls=[call_a, call_b])
    session = Session(session_id="s0", tasks=[task])

    findings = PrefixChurnDetector().analyze(session, _ctx(engine))

    assert findings == []


def test_guard_never_flags_a_genuinely_shrinking_prefix() -> None:
    engine = PricingEngine(PricingRegistry.load())
    call_a = _priced_call(engine, "a", input_tok=20_000, output_tok=300, start=0)
    # curr.input (500) is far below prev's total (20_300): a fresh, unrelated,
    # much smaller prompt — not a resend of the prior context.
    call_b = _priced_call(engine, "b", input_tok=500, output_tok=50, start=1)
    task = Task(task_id="t0", llm_calls=[call_a, call_b])
    session = Session(session_id="s0", tasks=[task])

    findings = PrefixChurnDetector().analyze(session, _ctx(engine))

    assert findings == []


def test_single_call_task_never_flagged() -> None:
    engine = PricingEngine(PricingRegistry.load())
    call_a = _priced_call(engine, "a", input_tok=50_000, output_tok=300, start=0)
    task = Task(task_id="t0", llm_calls=[call_a])
    session = Session(session_id="s0", tasks=[task])

    findings = PrefixChurnDetector().analyze(session, _ctx(engine))

    assert findings == []


@given(
    prior_input=st.integers(min_value=1, max_value=100_000),
    prior_output=st.integers(min_value=0, max_value=20_000),
    cache_read=st.integers(min_value=1, max_value=100_000),
)
def test_property_cache_read_always_suppresses_the_finding(
    prior_input: int, prior_output: int, cache_read: int
) -> None:
    engine = PricingEngine(PricingRegistry.load())
    call_a = _priced_call(engine, "a", input_tok=prior_input, output_tok=prior_output, start=0)
    # curr.input deliberately set to cover prior's full context, which would
    # otherwise trigger the finding, but cache_read is present on this call.
    call_b = _priced_call(
        engine,
        "b",
        input_tok=prior_input + prior_output + 1,
        output_tok=10,
        cache_read=cache_read,
        start=1,
    )
    task = Task(task_id="t0", llm_calls=[call_a, call_b])
    session = Session(session_id="s0", tasks=[task])

    findings = PrefixChurnDetector().analyze(session, _ctx(engine))

    assert findings == []


@given(
    prior_input=st.integers(min_value=100, max_value=100_000),
    prior_output=st.integers(min_value=0, max_value=20_000),
    shrink_factor=st.floats(min_value=0.01, max_value=0.99),
)
def test_property_never_flags_when_curr_input_is_smaller_than_priors_total(
    prior_input: int, prior_output: int, shrink_factor: float
) -> None:
    engine = PricingEngine(PricingRegistry.load())
    prior_total = prior_input + prior_output
    curr_input = max(0, int(prior_total * shrink_factor))
    call_a = _priced_call(engine, "a", input_tok=prior_input, output_tok=prior_output, start=0)
    call_b = _priced_call(engine, "b", input_tok=curr_input, output_tok=10, start=1)
    task = Task(task_id="t0", llm_calls=[call_a, call_b])
    session = Session(session_id="s0", tasks=[task])

    findings = PrefixChurnDetector().analyze(session, _ctx(engine))

    assert findings == []
