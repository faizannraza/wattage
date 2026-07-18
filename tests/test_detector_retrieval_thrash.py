from wattage.config import WattageConfig
from wattage.detectors.base import AnalysisContext
from wattage.detectors.retrieval_thrash import RetrievalThrashDetector
from wattage.models import Finding, Iteration, LLMCall, Loop, Session, Task, TokenUsage, ToolCall
from wattage.pricing.engine import PricingEngine
from wattage.pricing.registry import PricingRegistry


def _llm(span_id: str, engine: PricingEngine) -> LLMCall:
    call = LLMCall(
        span_id=span_id,
        provider="anthropic",
        model="claude-sonnet-4-6",
        usage=TokenUsage(input=500, output=50),
        start_ns=0,
    )
    call.cost = engine.price_call(call)
    return call


def _tool(span_id: str, name: str, args: dict[str, object], result: str) -> ToolCall:
    return ToolCall(span_id=span_id, name=name, args=args, args_hash="x", result=result, start_ns=0)


def _run(iterations: list[Iteration], engine: PricingEngine) -> list[Finding]:
    loop = Loop(loop_id="loop0", iterations=iterations, reached_success=False)
    task = Task(task_id="task0", loops=[loop])
    session = Session(session_id="s0", tasks=[task])
    ctx = AnalysisContext(pricing=engine, config=WattageConfig())
    return RetrievalThrashDetector().analyze(session, ctx)


def test_repeated_low_yield_search_is_flagged() -> None:
    engine = PricingEngine(PricingRegistry.load())
    iterations = [
        Iteration(
            index=i,
            llm_calls=[_llm(f"l{i}", engine)],
            tool_calls=[
                _tool(
                    f"t{i}",
                    "search_docs",
                    {"q": f"query variant {i}"},
                    "No relevant documents found matching the query.",
                )
            ],
        )
        for i in range(5)
    ]
    findings = _run(iterations, engine)
    assert len(findings) == 1
    assert findings[0].quality_risk.value == "review"
    assert findings[0].wasted_tokens > 0


def test_genuinely_useful_retrieval_each_turn_is_not_flagged() -> None:
    engine = PricingEngine(PricingRegistry.load())
    contents = [
        ("refund", "Refund policy: 30 days full refund if unused."),
        ("shipping", "Shipping: 2 business days via standard carrier."),
        ("warranty", "Warranty: 1 year manufacturer defects coverage."),
        ("returns", "Returns: use prepaid label included in original box."),
    ]
    iterations = [
        Iteration(
            index=i,
            llm_calls=[_llm(f"l{i}", engine)],
            tool_calls=[_tool(f"t{i}", "search_docs", {"q": q}, result)],
        )
        for i, (q, result) in enumerate(contents)
    ]
    assert _run(iterations, engine) == []


def test_too_few_retrieval_iterations_is_not_analyzed() -> None:
    engine = PricingEngine(PricingRegistry.load())
    iterations = [
        Iteration(
            index=i,
            llm_calls=[_llm(f"l{i}", engine)],
            tool_calls=[_tool(f"t{i}", "search_docs", {"q": "x"}, "no results")],
        )
        for i in range(2)
    ]
    assert _run(iterations, engine) == []


def test_non_retrieval_tool_calls_are_ignored() -> None:
    engine = PricingEngine(PricingRegistry.load())
    iterations = [
        Iteration(
            index=i,
            llm_calls=[_llm(f"l{i}", engine)],
            tool_calls=[_tool(f"t{i}", "write_file", {"path": f"/tmp/{i}"}, "written")],
        )
        for i in range(5)
    ]
    assert _run(iterations, engine) == []
