from wattage.config import DetectorsConfig, ModelMismatchConfig, WattageConfig
from wattage.detectors.base import AnalysisContext
from wattage.detectors.model_mismatch import ModelMismatchDetector
from wattage.models import Iteration, LLMCall, Loop, Session, Task, TokenUsage, ToolCall
from wattage.pricing.engine import PricingEngine
from wattage.pricing.registry import PricingRegistry

_PASSING_QUALITY_MAP = {"downgrade_evals": {"tool_select@claude-haiku-4-5": {"pass_rate": 0.97}}}


def _tool_select_session(engine: PricingEngine, model: str = "claude-opus-4-8") -> Session:
    call = LLMCall(
        span_id="l0",
        provider="anthropic",
        model=model,
        usage=TokenUsage(input=1000, output=30),
        start_ns=0,
    )
    call.cost = engine.price_call(call)
    tool_call = ToolCall(span_id="t0", name="search_docs", args={}, args_hash="x", start_ns=0)
    loop = Loop(
        loop_id="loop0",
        iterations=[Iteration(index=0, llm_calls=[call], tool_calls=[tool_call])],
        reached_success=False,
    )
    task = Task(task_id="task0", loops=[loop])
    return Session(session_id="s0", tasks=[task])


def test_no_finding_without_quality_map_by_default() -> None:
    engine = PricingEngine(PricingRegistry.load())
    ctx = AnalysisContext(pricing=engine, config=WattageConfig())
    assert ModelMismatchDetector().analyze(_tool_select_session(engine), ctx) == []


def test_finding_produced_with_confirmed_quality_map() -> None:
    engine = PricingEngine(PricingRegistry.load())
    ctx = AnalysisContext(pricing=engine, config=WattageConfig(), quality_map=_PASSING_QUALITY_MAP)
    findings = ModelMismatchDetector().analyze(_tool_select_session(engine), ctx)

    assert len(findings) == 1
    finding = findings[0]
    expected_wasted = 1000 * (5.0e-6 - 1.0e-6) + 30 * (25.0e-6 - 5.0e-6)
    assert finding.wasted_dollars == expected_wasted
    assert finding.quality_risk.value == "review"
    assert "97%" in finding.evidence


def test_low_pass_rate_still_suppresses_the_finding() -> None:
    engine = PricingEngine(PricingRegistry.load())
    low_confidence_map = {"downgrade_evals": {"tool_select@claude-haiku-4-5": {"pass_rate": 0.5}}}
    ctx = AnalysisContext(pricing=engine, config=WattageConfig(), quality_map=low_confidence_map)
    assert ModelMismatchDetector().analyze(_tool_select_session(engine), ctx) == []


def test_relaxed_guard_allows_the_heuristic_alone() -> None:
    engine = PricingEngine(PricingRegistry.load())
    config = WattageConfig(
        detectors=DetectorsConfig(model_mismatch=ModelMismatchConfig(require_quality_map=False))
    )
    ctx = AnalysisContext(pricing=engine, config=config)
    findings = ModelMismatchDetector().analyze(_tool_select_session(engine), ctx)
    assert len(findings) == 1


def test_non_tool_selecting_iteration_is_never_flagged() -> None:
    engine = PricingEngine(PricingRegistry.load())
    call = LLMCall(
        span_id="l0",
        provider="anthropic",
        model="claude-opus-4-8",
        usage=TokenUsage(input=1000, output=30),
        start_ns=0,
    )
    call.cost = engine.price_call(call)
    task = Task(task_id="task0", llm_calls=[call])  # no tool calls at all
    session = Session(session_id="s0", tasks=[task])
    ctx = AnalysisContext(pricing=engine, config=WattageConfig(), quality_map=_PASSING_QUALITY_MAP)
    assert ModelMismatchDetector().analyze(session, ctx) == []


def test_already_on_the_cheap_model_is_never_flagged() -> None:
    engine = PricingEngine(PricingRegistry.load())
    session = _tool_select_session(engine, model="claude-haiku-4-5")
    ctx = AnalysisContext(pricing=engine, config=WattageConfig(), quality_map=_PASSING_QUALITY_MAP)
    assert ModelMismatchDetector().analyze(session, ctx) == []


def test_large_output_step_is_not_treated_as_tool_select() -> None:
    engine = PricingEngine(PricingRegistry.load())
    call = LLMCall(
        span_id="l0",
        provider="anthropic",
        model="claude-opus-4-8",
        usage=TokenUsage(input=1000, output=5000),  # far above simple_output_ceiling
        start_ns=0,
    )
    call.cost = engine.price_call(call)
    tool_call = ToolCall(span_id="t0", name="search_docs", args={}, args_hash="x", start_ns=0)
    loop = Loop(
        loop_id="loop0",
        iterations=[Iteration(index=0, llm_calls=[call], tool_calls=[tool_call])],
        reached_success=False,
    )
    task = Task(task_id="task0", loops=[loop])
    session = Session(session_id="s0", tasks=[task])
    ctx = AnalysisContext(pricing=engine, config=WattageConfig(), quality_map=_PASSING_QUALITY_MAP)
    assert ModelMismatchDetector().analyze(session, ctx) == []
