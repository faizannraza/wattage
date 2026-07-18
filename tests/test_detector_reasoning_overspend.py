from wattage.config import WattageConfig
from wattage.detectors.base import AnalysisContext
from wattage.detectors.reasoning_overspend import ReasoningOverspendDetector
from wattage.models import LLMCall, Session, Task, TokenUsage
from wattage.pricing.engine import PricingEngine
from wattage.pricing.registry import PricingRegistry

_OUTPUT_RATE = 15.0e-6  # claude-sonnet-4-6


def _session(reasoning: int, output_tok: int, engine: PricingEngine) -> Session:
    call = LLMCall(
        span_id="l0",
        provider="anthropic",
        model="claude-sonnet-4-6",
        usage=TokenUsage(input=500, output=output_tok, reasoning=reasoning),
        start_ns=0,
    )
    call.cost = engine.price_call(call)
    task = Task(task_id="t", llm_calls=[call])
    return Session(session_id="s", tasks=[task])


def test_excess_reasoning_on_a_simple_step_is_flagged_and_quantified() -> None:
    engine = PricingEngine(PricingRegistry.load())
    ctx = AnalysisContext(pricing=engine, config=WattageConfig())
    findings = ReasoningOverspendDetector().analyze(_session(2000, 30, engine), ctx)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.wasted_tokens == 1500  # 2000 - 500 ceiling
    assert finding.wasted_dollars == 1500 * _OUTPUT_RATE
    assert finding.severity.value == "high"
    assert finding.quality_risk.value == "review"


def test_reasoning_under_ceiling_is_not_flagged() -> None:
    engine = PricingEngine(PricingRegistry.load())
    ctx = AnalysisContext(pricing=engine, config=WattageConfig())
    assert ReasoningOverspendDetector().analyze(_session(300, 30, engine), ctx) == []


def test_large_final_output_suggests_genuine_complexity_and_is_not_flagged() -> None:
    engine = PricingEngine(PricingRegistry.load())
    ctx = AnalysisContext(pricing=engine, config=WattageConfig())
    assert ReasoningOverspendDetector().analyze(_session(2000, 2000, engine), ctx) == []


def test_moderate_excess_is_medium_severity() -> None:
    engine = PricingEngine(PricingRegistry.load())
    ctx = AnalysisContext(pricing=engine, config=WattageConfig())
    findings = ReasoningOverspendDetector().analyze(_session(700, 30, engine), ctx)
    assert len(findings) == 1
    assert findings[0].severity.value == "medium"
