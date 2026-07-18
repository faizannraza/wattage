"""Phase 0 pipeline: ingest -> sessionize -> price -> assemble a Report.

No detectors run yet (Phase 1), so findings are empty and the score is an
honest placeholder rather than a computed grade.
"""

from __future__ import annotations

from datetime import datetime, timezone

from wattage.adapters.otlp_file import OTLPFileAdapter
from wattage.models import Report, Score
from wattage.pricing.engine import PricingEngine
from wattage.pricing.registry import PricingRegistry
from wattage.sessionize import sessionize

_PLACEHOLDER_SCORE = Score(
    efficiency=100,
    grade="A",
    waste_ratio=0.0,
    quality_factor=1.0,
    quality_measured=False,
    recoverable_dollars=0.0,
)


def build_report(source: str, pricing_override: str | None = None) -> Report:
    adapter = OTLPFileAdapter()
    raw_spans = list(adapter.read(source))
    trace = sessionize(raw_spans, source=source)

    registry = PricingRegistry.load(overrides_path=pricing_override)
    engine = PricingEngine(registry)

    token_breakdown = {
        "input": 0,
        "output": 0,
        "cache_read": 0,
        "cache_creation": 0,
        "reasoning": 0,
    }
    total_dollars = 0.0

    for session in trace.sessions:
        for task in session.tasks:
            calls = list(task.llm_calls)
            for loop in task.loops:
                for iteration in loop.iterations:
                    calls.extend(iteration.llm_calls)
            for call in calls:
                call.cost = engine.price_call(call)
                token_breakdown["input"] += call.usage.input
                token_breakdown["output"] += call.usage.output
                token_breakdown["cache_read"] += call.usage.cache_read
                token_breakdown["cache_creation"] += call.usage.cache_creation
                token_breakdown["reasoning"] += call.usage.reasoning
                total_dollars += call.cost.total

    return Report(
        trace_source=source,
        total_dollars=total_dollars,
        token_breakdown=token_breakdown,
        findings=[],
        score=_PLACEHOLDER_SCORE,
        pricing_version=registry.version,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
