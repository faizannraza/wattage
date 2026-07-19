"""retrieval_thrash (doc §4.3): repeated retrieval that isn't yielding new
evidence, or oversized/low-relevance context stuffing.

Reuses the convergence embedder (ctx.embedder) for evidence-gain-per-
iteration — the same novelty computation as the convergence engine's E
signal, scoped specifically to retrieval activity: RetrievalCall entries,
plus tool calls whose name looks like a retrieval operation
(search/retrieve/query/lookup/find), since this project's own real-trace
validation (benchmarks/traces/) confirmed most real agent frameworks
implement "retrieval" as a plain tool call rather than a dedicated
`embeddings`-kind span.

Two doc-specified signals are honestly left unimplemented rather than
faked: "relevance yield" needs per-chunk relevance scores
(RetrievalCall.chunks can carry them, but no adapter populates them yet),
and "SLO-awareness" needs a latency budget input nothing currently supplies.
Both are documented gaps for a future adapter/config enhancement.

quality_risk is "review" (doc §6.3 explicitly categorizes "aggressive
retrieval cuts" as review-risk) — capping retrieval could hurt a genuinely
hard query that needed the extra iterations, so this never counts toward
the efficiency score unless a --quality map confirms the cut is safe.
"""

from __future__ import annotations

from wattage.convergence.embed import build_embedder
from wattage.detectors.base import AnalysisContext
from wattage.models import Finding, Iteration, Loop, QualityRisk, Session, Severity, ToolCall
from wattage.pricing.registry import ModelPrice, UnknownModelError

_RETRIEVAL_NAME_HINTS = ("search", "retrieve", "query", "lookup", "find")


def _is_retrieval_like(tool_call: ToolCall) -> bool:
    name = tool_call.name.lower()
    return any(hint in name for hint in _RETRIEVAL_NAME_HINTS)


def _is_retrieval_iteration(iteration: Iteration) -> bool:
    return bool(iteration.retrievals) or any(_is_retrieval_like(tc) for tc in iteration.tool_calls)


def _retrieval_info(iteration: Iteration) -> str:
    parts = [tc.result for tc in iteration.tool_calls if _is_retrieval_like(tc) and tc.result]
    for retrieval in iteration.retrievals:
        for chunk in retrieval.chunks:
            text = chunk.get("text") if isinstance(chunk, dict) else None
            if text:
                parts.append(str(text))
    return "\n".join(parts)


def _representative_price(loop: Loop, ctx: AnalysisContext) -> ModelPrice | None:
    for iteration in loop.iterations:
        for call in iteration.llm_calls:
            try:
                return ctx.pricing.registry.get(call.provider, call.model)
            except UnknownModelError:
                continue
    return None


class RetrievalThrashDetector:
    id = "retrieval_thrash"
    default_enabled = True

    def analyze(self, session: Session, ctx: AnalysisContext) -> list[Finding]:
        cfg = ctx.config.detectors.retrieval_thrash
        if not cfg.enabled:
            return []
        findings: list[Finding] = []
        for task in session.tasks:
            for loop in task.loops:
                finding = self._analyze_loop(loop, ctx)
                if finding is not None:
                    findings.append(finding)
        return findings

    def _analyze_loop(self, loop: Loop, ctx: AnalysisContext) -> Finding | None:
        cfg = ctx.config.detectors.retrieval_thrash
        embedder = ctx.embedder or build_embedder("local")

        retrieval_iters = [it for it in loop.iterations if _is_retrieval_iteration(it)]
        floor = max(2, cfg.max_iterations_soft)
        if len(retrieval_iters) < floor:
            return None  # not enough retrieval activity to judge thrash

        prior_infos: list[str] = []
        low_yield_iterations: list[Iteration] = []
        for it in retrieval_iters:
            info = _retrieval_info(it)
            gain = embedder.novelty(info, prior_infos)
            if gain <= cfg.relevance_threshold:
                low_yield_iterations.append(it)
            if info:
                prior_infos.append(info)

        if len(low_yield_iterations) < floor:
            return None  # most retrieval iterations did yield new evidence

        price = _representative_price(loop, ctx)
        wasted_tokens = 0
        wasted_dollars = 0.0
        span_ids: list[str] = []
        for it in low_yield_iterations:
            for tc in it.tool_calls:
                if _is_retrieval_like(tc) and tc.result:
                    tokens = len(tc.result) // 4
                    wasted_tokens += tokens
                    if price is not None:
                        wasted_dollars += tokens * price.input
                    span_ids.append(tc.span_id)

        if wasted_tokens == 0:
            return None

        severity = (
            Severity.high if len(low_yield_iterations) >= len(retrieval_iters) else Severity.medium
        )
        return Finding(
            id=self.id,
            severity=severity,
            wasted_tokens=wasted_tokens,
            wasted_dollars=wasted_dollars,
            quality_risk=QualityRisk.review,
            evidence=(
                f"{len(low_yield_iterations)} of {len(retrieval_iters)} retrieval iterations "
                f"in loop {loop.loop_id} yielded little to no new evidence"
            ),
            fix=(
                "Right-size top_k, add a relevance/rerank filter, or cap retrieval iterations "
                "once the marginal chunk stops adding evidence."
            ),
            span_ids=span_ids,
        )
