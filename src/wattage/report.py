"""Phase 1 pipeline: ingest -> sessionize -> price -> detect -> score -> Report."""

from __future__ import annotations

from datetime import datetime, timezone

from wattage.adapters.otlp_file import OTLPFileAdapter
from wattage.config import WattageConfig
from wattage.convergence.embed import build_embedder
from wattage.detectors.base import AnalysisContext, load_detectors, ordered_llm_calls
from wattage.models import Report
from wattage.pricing.engine import PricingEngine
from wattage.pricing.registry import PricingRegistry
from wattage.scoring.quality import compute_quality_factor
from wattage.scoring.score import compute_score
from wattage.sessionize import sessionize


def build_report(
    source: str,
    pricing_override: str | None = None,
    config: WattageConfig | None = None,
) -> Report:
    config = config or WattageConfig()

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

    # Price every call first: detectors (cache_gap, prefix_churn's ratio-based
    # severity) read call.cost, so pricing must happen before detection runs.
    for session in trace.sessions:
        for task in session.tasks:
            for call in ordered_llm_calls(task):
                call.cost = engine.price_call(call)
                token_breakdown["input"] += call.usage.input
                token_breakdown["output"] += call.usage.output
                token_breakdown["cache_read"] += call.usage.cache_read
                token_breakdown["cache_creation"] += call.usage.cache_creation
                token_breakdown["reasoning"] += call.usage.reasoning
                total_dollars += call.cost.total

    # Built once and shared: retrieval_thrash (Phase 2.10) reuses the same
    # embedder instance rather than each detector loading its own model.
    embedder = build_embedder(config.detectors.nonconvergence.embed)
    ctx = AnalysisContext(pricing=engine, config=config, embedder=embedder)
    detectors = load_detectors(config)
    findings = [
        finding
        for session in trace.sessions
        for detector in detectors
        for finding in detector.analyze(session, ctx)
    ]

    quality_factor, quality_measured = compute_quality_factor(None)
    score = compute_score(
        findings=findings,
        total_dollars=total_dollars,
        quality_factor=quality_factor,
        quality_measured=quality_measured,
    )

    return Report(
        trace_source=source,
        total_dollars=total_dollars,
        token_breakdown=token_breakdown,
        findings=findings,
        score=score,
        pricing_version=registry.version,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
