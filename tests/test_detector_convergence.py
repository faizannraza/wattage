import pytest

from wattage.config import WattageConfig
from wattage.detectors.base import AnalysisContext
from wattage.detectors.convergence import NonConvergenceDetector
from wattage.models import Finding, Iteration, LLMCall, Loop, Session, Task, TokenUsage, ToolCall
from wattage.pricing.engine import PricingEngine
from wattage.pricing.registry import PricingRegistry


def _llm(
    span_id: str, engine: PricingEngine, input_tok: int = 500, output_tok: int = 50
) -> LLMCall:
    call = LLMCall(
        span_id=span_id,
        provider="anthropic",
        model="claude-sonnet-4-6",
        usage=TokenUsage(input=input_tok, output=output_tok),
        start_ns=0,
    )
    call.cost = engine.price_call(call)
    return call


def _tool(span_id: str, name: str, args: dict[str, object], result: str) -> ToolCall:
    return ToolCall(span_id=span_id, name=name, args=args, args_hash="x", result=result, start_ns=0)


def _run(loop: Loop, engine: PricingEngine) -> list[Finding]:
    task = Task(task_id="task0", loops=[loop])
    session = Session(session_id="s0", tasks=[task])
    ctx = AnalysisContext(pricing=engine, config=WattageConfig())
    return NonConvergenceDetector().analyze(session, ctx)


@pytest.fixture
def engine() -> PricingEngine:
    return PricingEngine(PricingRegistry.load())


def test_short_loop_below_min_iterations_is_never_analyzed(engine: PricingEngine) -> None:
    iterations = [
        Iteration(
            index=i, llm_calls=[_llm(f"l{i}", engine)], tool_calls=[_tool(f"t{i}", "x", {}, "r")]
        )
        for i in range(2)
    ]
    loop = Loop(loop_id="loop0", iterations=iterations, reached_success=False)
    assert _run(loop, engine) == []


def test_loop_that_reached_success_is_never_flagged(engine: PricingEngine) -> None:
    """Even if the middle looked repetitive, doc §5.5 says never punish success."""
    iterations = [
        Iteration(
            index=i,
            llm_calls=[_llm(f"l{i}", engine)],
            tool_calls=[_tool(f"t{i}", "run_tests", {"attempt": i}, "FAILED: same error")],
        )
        for i in range(5)
    ]
    loop = Loop(loop_id="loop0", iterations=iterations, reached_success=True)
    assert _run(loop, engine) == []


def test_thrashing_with_fuzzy_args_is_caught_and_quantified(engine: PricingEngine) -> None:
    """The baseline-blind-spot case: incrementing 'attempt' defeats exact-hash
    matching, but repetitive near-identical failures still get caught. Flat
    (non-growing) input tokens keep this "thrashing" rather than "stalled" —
    see the growing-context variant below."""
    iterations = [
        Iteration(
            index=i,
            llm_calls=[_llm(f"l{i}", engine)],
            tool_calls=[
                _tool(f"t{i}", "run_tests", {"attempt": i}, "FAILED: assertion error at line 42")
            ],
        )
        for i in range(5)
    ]
    loop = Loop(loop_id="loop0", iterations=iterations, reached_success=False)

    findings = _run(loop, engine)
    assert len(findings) == 1
    assert findings[0].subtype == "thrashing"
    assert findings[0].wasted_tokens > 0
    assert findings[0].wasted_dollars > 0


def test_stalled_loop_with_fuzzy_args_and_growing_context_is_caught(engine: PricingEngine) -> None:
    """The doc's stalled signature specifically: action stays near-static
    (same tool, fuzzy-varying args — an exact-match baseline sees zero exact
    repeats) AND context keeps growing each turn, while results stay
    boilerplate (no real evidence). This is what separates "stalled" from
    plain "thrashing" (test above): same repetitive non-action, but here
    it's also getting progressively more expensive."""
    iterations = []
    running_input = 2000
    for i in range(5):
        running_input += 8000
        iterations.append(
            Iteration(
                index=i,
                llm_calls=[_llm(f"l{i}", engine, input_tok=running_input, output_tok=30)],
                tool_calls=[_tool(f"t{i}", "run_tests", {"attempt": i}, "FAILED: same error")],
            )
        )
    loop = Loop(loop_id="loop0", iterations=iterations, reached_success=False)

    findings = _run(loop, engine)
    assert len(findings) == 1
    assert findings[0].subtype == "stalled"


def test_oscillating_between_two_tools_is_caught(engine: PricingEngine) -> None:
    iterations = []
    for i in range(6):
        name = "check_status" if i % 2 == 0 else "retry_action"
        result = "status: pending, no change" if name == "check_status" else "retried, no effect"
        iterations.append(
            Iteration(
                index=i,
                llm_calls=[_llm(f"l{i}", engine, input_tok=500 + i * 50)],
                tool_calls=[_tool(f"t{i}", name, {"id": i}, result)],
            )
        )
    loop = Loop(loop_id="loop0", iterations=iterations, reached_success=False)

    findings = _run(loop, engine)
    assert len(findings) == 1
    assert findings[0].subtype == "oscillating"


def test_genuinely_productive_loop_is_not_flagged(engine: PricingEngine) -> None:
    iterations = [
        Iteration(
            index=0,
            llm_calls=[_llm("l0", engine, 500)],
            tool_calls=[
                _tool(
                    "t0",
                    "search_docs",
                    {"q": "refund policy"},
                    "Refund policy: full refund within 30 days if item is unused.",
                )
            ],
        ),
        Iteration(
            index=1,
            llm_calls=[_llm("l1", engine, 700)],
            tool_calls=[
                _tool(
                    "t1",
                    "search_docs",
                    {"q": "shipping policy"},
                    "Shipping policy: orders ship within 2 business days via standard carrier.",
                )
            ],
        ),
        Iteration(index=2, llm_calls=[_llm("l2", engine, 900)]),
    ]
    loop = Loop(loop_id="loop0", iterations=iterations, reached_success=False)

    assert _run(loop, engine) == []


def test_wasted_tokens_only_count_iterations_after_last_productive(engine: PricingEngine) -> None:
    productive = Iteration(
        index=0,
        llm_calls=[_llm("l0", engine, 500, 50)],
        tool_calls=[
            _tool("t0", "search_docs", {"q": "a"}, "genuinely novel and useful information here")
        ],
    )
    bad = [
        Iteration(
            index=i,
            llm_calls=[_llm(f"l{i}", engine, 500, 50)],
            tool_calls=[_tool(f"t{i}", "run_tests", {"attempt": i}, "FAILED: same error")],
        )
        for i in range(1, 5)
    ]
    loop = Loop(loop_id="loop0", iterations=[productive, *bad], reached_success=False)

    findings = _run(loop, engine)
    assert len(findings) == 1
    # Wasted tokens must come only from the 4 bad iterations, not the productive one.
    expected_tokens = sum((500 + 50) for _ in bad)
    assert findings[0].wasted_tokens <= expected_tokens
    assert findings[0].wasted_tokens > 0
