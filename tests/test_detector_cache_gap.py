from hypothesis import given
from hypothesis import strategies as st

from wattage.config import WattageConfig
from wattage.detectors.base import AnalysisContext
from wattage.detectors.cache_gap import CacheGapDetector
from wattage.models import LLMCall, Session, Task, TokenUsage
from wattage.pricing.engine import PricingEngine
from wattage.pricing.registry import PricingRegistry

_INPUT_RATE = 3.0e-6  # claude-sonnet-4-6
_WRITE_MULT = 1.25
_PREMIUM_PER_TOKEN = _INPUT_RATE * (_WRITE_MULT - 1.0)


def _call(
    engine: PricingEngine,
    span_id: str,
    cache_creation: int = 0,
    cache_read: int = 0,
    start: int = 0,
) -> LLMCall:
    call = LLMCall(
        span_id=span_id,
        provider="anthropic",
        model="claude-sonnet-4-6",
        usage=TokenUsage(
            input=1000, output=100, cache_creation=cache_creation, cache_read=cache_read
        ),
        start_ns=start,
    )
    call.cost = engine.price_call(call)
    return call


def _ctx(engine: PricingEngine) -> AnalysisContext:
    return AnalysisContext(pricing=engine, config=WattageConfig())


def test_write_without_any_read_is_fully_wasted() -> None:
    engine = PricingEngine(PricingRegistry.load())
    task = Task(task_id="t0", llm_calls=[_call(engine, "a", cache_creation=5000)])
    session = Session(session_id="s0", tasks=[task])

    findings = CacheGapDetector().analyze(session, _ctx(engine))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.wasted_tokens == 5000
    assert finding.wasted_dollars == 5000 * _PREMIUM_PER_TOKEN
    assert finding.severity.value == "high"


def test_partial_redemption_scales_the_waste_by_unredeemed_fraction() -> None:
    engine = PricingEngine(PricingRegistry.load())
    task = Task(
        task_id="t1",
        llm_calls=[
            _call(engine, "a", cache_creation=5000, start=0),
            _call(engine, "b", cache_read=2000, start=1),
        ],
    )
    session = Session(session_id="s1", tasks=[task])

    findings = CacheGapDetector().analyze(session, _ctx(engine))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.wasted_tokens == 3000  # 5000 * (1 - 2000/5000)
    assert finding.wasted_dollars == 5000 * _PREMIUM_PER_TOKEN * 0.6
    assert finding.severity.value == "medium"


def test_full_redemption_is_not_flagged() -> None:
    engine = PricingEngine(PricingRegistry.load())
    task = Task(
        task_id="t2",
        llm_calls=[
            _call(engine, "a", cache_creation=5000, start=0),
            _call(engine, "b", cache_read=6000, start=1),
        ],
    )
    session = Session(session_id="s2", tasks=[task])

    assert CacheGapDetector().analyze(session, _ctx(engine)) == []


def test_no_caching_attempted_is_not_flagged_here() -> None:
    """Caching never attempted at all is prefix_churn's territory, not cache_gap's."""
    engine = PricingEngine(PricingRegistry.load())
    task = Task(task_id="t3", llm_calls=[_call(engine, "a")])
    session = Session(session_id="s3", tasks=[task])

    assert CacheGapDetector().analyze(session, _ctx(engine)) == []


@given(
    cache_creation=st.integers(min_value=1, max_value=1_000_000),
    read_ratio=st.floats(min_value=1.0, max_value=5.0),
)
def test_property_reads_at_or_above_writes_never_flag(
    cache_creation: int, read_ratio: float
) -> None:
    engine = PricingEngine(PricingRegistry.load())
    cache_read = int(cache_creation * read_ratio)
    task = Task(
        task_id="t4",
        llm_calls=[
            _call(engine, "a", cache_creation=cache_creation, start=0),
            _call(engine, "b", cache_read=cache_read, start=1),
        ],
    )
    session = Session(session_id="s4", tasks=[task])

    assert CacheGapDetector().analyze(session, _ctx(engine)) == []
