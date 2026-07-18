"""nonconvergence (doc §4.4/§5): agents thrashing/oscillating/stalling in
loops without making real progress — the convergence engine's headline
detector. Classification comes from convergence/classify.py; this module
wires it to a session's loops and implements the wasted-token attribution
from §5.4 (everything after the last iteration whose progress crossed
theta_prog).

"Never punish a loop that ultimately succeeded" (§5.5) is implemented via
sessionize's reached_success heuristic: such loops are skipped entirely
rather than attempting to pinpoint a post-success tail, which would need
semantic judgment (the optional judge, off by default) this MVP doesn't
invoke automatically.
"""

from __future__ import annotations

from wattage.config import NonConvergenceConfig
from wattage.convergence.classify import (
    ClassificationThresholds,
    ConvergenceWeights,
    LoopClass,
    classify_loop,
    combine_progress,
    last_productive_index,
)
from wattage.convergence.embed import build_embedder
from wattage.convergence.signals import compute_iteration_signals
from wattage.detectors.base import AnalysisContext
from wattage.models import Finding, Loop, QualityRisk, Session, Severity

_FIX_BY_CLASS = {
    LoopClass.thrashing: (
        "Add a convergence stop after repeated non-productive iterations; "
        "disambiguate tool success/failure states so the agent can tell it "
        "isn't making progress."
    ),
    LoopClass.oscillating: (
        "Break the cycle: force a strategy switch after N repeats of the same "
        "alternating pattern, or summarize-and-restart."
    ),
    LoopClass.stalled: (
        "Context kept growing with no new evidence — cap iterations, or add a "
        "convergence check that stops the loop once retrieved/tool content "
        "stops changing."
    ),
}

_SEVERITY_BY_CLASS = {
    LoopClass.thrashing: Severity.medium,
    LoopClass.oscillating: Severity.high,
    LoopClass.stalled: Severity.high,
}


class NonConvergenceDetector:
    id = "nonconvergence"
    default_enabled = True

    def analyze(self, session: Session, ctx: AnalysisContext) -> list[Finding]:
        cfg = ctx.config.detectors.nonconvergence
        if not cfg.enabled:
            return []
        findings: list[Finding] = []
        for task in session.tasks:
            for loop in task.loops:
                finding = self._analyze_loop(loop, task.task_id, cfg, ctx)
                if finding is not None:
                    findings.append(finding)
        return findings

    def _analyze_loop(
        self,
        loop: Loop,
        task_id: str,
        cfg: NonConvergenceConfig,
        ctx: AnalysisContext,
    ) -> Finding | None:
        iterations = loop.iterations
        if len(iterations) < cfg.min_iterations:
            return None
        if loop.reached_success:
            return None  # never punish a loop that ultimately succeeded (doc §5.5)

        embedder = ctx.embedder or build_embedder(cfg.embed)
        weights = ConvergenceWeights(
            E=cfg.weights.E, S=cfg.weights.S, P=cfg.weights.P, O=cfg.weights.O, G=cfg.weights.G
        )
        thresholds = ClassificationThresholds(
            theta_prog=cfg.theta_prog,
            consecutive_k=cfg.consecutive_k,
            oscillation_threshold=cfg.oscillation_threshold,
            stall_evidence_threshold=cfg.stall_evidence_threshold,
            stall_state_threshold=cfg.stall_state_threshold,
            stall_growth_threshold=cfg.stall_growth_threshold,
        )

        signals = compute_iteration_signals(
            iterations,
            embedder,
            goal_signal=loop.goal_signal,
            oscillation_window=cfg.osc_window,
            max_period=cfg.max_period,
            exempt_tools=frozenset(cfg.exempt_tools),
        )
        progress_scores = [combine_progress(s, weights) for s in signals]
        loop_class = classify_loop(signals, progress_scores, thresholds)
        if loop_class == LoopClass.productive:
            return None

        last_prod = last_productive_index(progress_scores, cfg.theta_prog)
        wasted_from = 0 if last_prod is None else last_prod + 1
        wasted_iterations = iterations[wasted_from:]

        wasted_tokens = sum(it.tokens().total() for it in wasted_iterations)
        wasted_dollars = sum(it.cost() for it in wasted_iterations)
        span_ids = [call.span_id for it in wasted_iterations for call in it.llm_calls] + [
            call.span_id for it in wasted_iterations for call in it.tool_calls
        ]

        return Finding(
            id=self.id,
            subtype=loop_class.value,
            severity=_SEVERITY_BY_CLASS[loop_class],
            wasted_tokens=wasted_tokens,
            wasted_dollars=wasted_dollars,
            quality_risk=QualityRisk.none,
            evidence=(
                f"Loop {loop.loop_id} in task {task_id} classified {loop_class.value}: "
                f"{len(wasted_iterations)} of {len(iterations)} iterations came after the "
                f"last productive one (progress scores: {[round(p, 2) for p in progress_scores]})"
            ),
            fix=_FIX_BY_CLASS[loop_class],
            span_ids=span_ids,
        )
