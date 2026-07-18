import hashlib
import json

from hypothesis import given
from hypothesis import strategies as st

from wattage.config import WattageConfig
from wattage.detectors.base import AnalysisContext
from wattage.detectors.redundant_tool_calls import RedundantToolCallsDetector
from wattage.models import Finding, Iteration, LLMCall, Loop, Session, Task, TokenUsage, ToolCall
from wattage.pricing.engine import PricingEngine
from wattage.pricing.registry import PricingRegistry


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _tool_call(
    span_id: str, name: str, args: dict[str, object], result: str | None = None, start: int = 0
) -> ToolCall:
    return ToolCall(
        span_id=span_id,
        name=name,
        args=args,
        args_hash=_hash(args),
        result=result,
        result_hash=_hash(result) if result is not None else None,
        start_ns=start,
    )


def _llm_call(engine: PricingEngine, span_id: str, start: int = 0) -> LLMCall:
    call = LLMCall(
        span_id=span_id,
        provider="anthropic",
        model="claude-sonnet-4-6",
        usage=TokenUsage(input=500, output=50),
        start_ns=start,
    )
    call.cost = engine.price_call(call)
    return call


def _run(engine: PricingEngine, tool_calls: list[ToolCall]) -> list[Finding]:
    iterations = [
        Iteration(index=i, llm_calls=[_llm_call(engine, f"l{i}", start=i * 10)], tool_calls=[tc])
        for i, tc in enumerate(tool_calls)
    ]
    task = Task(task_id="t0", loops=[Loop(loop_id="t0:loop0", iterations=iterations)])
    session = Session(session_id="s0", tasks=[task])
    ctx = AnalysisContext(pricing=engine, config=WattageConfig())
    return RedundantToolCallsDetector().analyze(session, ctx)


def test_exact_duplicate_with_same_result_is_flagged() -> None:
    engine = PricingEngine(PricingRegistry.load())
    findings = _run(
        engine,
        [
            _tool_call("a", "search_docs", {"q": "x"}, result="same result text here"),
            _tool_call("b", "search_docs", {"q": "x"}, result="same result text here"),
        ],
    )
    assert len(findings) == 1
    assert findings[0].span_ids == ["a", "b"]
    assert findings[0].wasted_tokens == len("same result text here") // 4


def test_same_args_but_changed_result_is_not_redundant() -> None:
    """A polling call whose status actually changed is not waste."""
    engine = PricingEngine(PricingRegistry.load())
    findings = _run(
        engine,
        [
            _tool_call("a", "check_status", {"id": 1}, result="pending"),
            _tool_call("b", "check_status", {"id": 1}, result="done"),
        ],
    )
    assert findings == []


def test_exempt_tool_never_flagged() -> None:
    engine = PricingEngine(PricingRegistry.load())
    findings = _run(
        engine,
        [
            _tool_call("a", "poll_status", {"id": 1}, result="x"),
            _tool_call("b", "poll_status", {"id": 1}, result="x"),
        ],
    )
    assert findings == []


def test_fuzzy_mode_collapses_near_identical_numeric_args() -> None:
    engine = PricingEngine(PricingRegistry.load())
    findings = _run(
        engine,
        [
            _tool_call("a", "calc", {"x": 1.001}, result="42"),
            _tool_call("b", "calc", {"x": 1.002}, result="42"),
        ],
    )
    assert len(findings) == 1


def test_duplicate_outside_the_window_is_not_flagged() -> None:
    engine = PricingEngine(PricingRegistry.load())
    fillers = [_tool_call(f"f{i}", "other_tool", {"i": i}, result="r") for i in range(6)]
    findings = _run(
        engine,
        [_tool_call("a", "search_docs", {"q": "x"}, result="same")]
        + fillers
        + [_tool_call("b", "search_docs", {"q": "x"}, result="same")],
    )
    assert findings == []


@given(
    first_status=st.text(min_size=1, max_size=20),
    second_status=st.text(min_size=1, max_size=20),
)
def test_property_polling_with_any_distinct_statuses_is_never_flagged(
    first_status: str, second_status: str
) -> None:
    if first_status == second_status:
        return  # that's the "genuinely redundant" case, not polling
    engine = PricingEngine(PricingRegistry.load())
    findings = _run(
        engine,
        [
            _tool_call("a", "poll_status", {"id": 1}, result=first_status),
            _tool_call("b", "poll_status", {"id": 1}, result=second_status),
        ],
    )
    assert findings == []


@given(status=st.text(min_size=1, max_size=20))
def test_property_non_exempt_tool_with_changing_result_never_flagged(status: str) -> None:
    engine = PricingEngine(PricingRegistry.load())
    findings = _run(
        engine,
        [
            _tool_call("a", "check_status", {"id": 1}, result=status),
            _tool_call("b", "check_status", {"id": 1}, result=status + "-changed"),
        ],
    )
    assert findings == []
