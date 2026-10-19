"""tool_result_bloat: oversized tool results dumped into the context.

A tool that returns 200KB of raw output (a whole file, a full API response,
an uncapped shell command) doesn't just cost once — that text rides along
in every subsequent model call's context for the rest of the loop. This is
the single most common waste pattern in coding-agent sessions, and the fix
is always at the tool boundary: truncate, paginate, or summarize before
returning.

The dollar figure prices the excess (beyond the configured ceiling) at the
task's input rate using the ~4-chars-per-token approximation, once — a
deliberate UNDER-estimate, since the real cost multiplies by the number of
later turns carrying it. It's still an estimate (basis `estimated`), capped
at the task's actual billed dollars, and never counts toward the grade.

Findings aggregate per (task, tool): one oversized tool reported once with
its worst offender, not one finding per call.
"""

from __future__ import annotations

from wattage.detectors.base import (
    AnalysisContext,
    ordered_llm_calls,
    ordered_tool_calls,
    rate_card_for,
)
from wattage.models import Finding, FindingBasis, QualityRisk, Session, Severity, ToolCall
from wattage.pricing.registry import UnknownModelError

_CHARS_PER_TOKEN = 4


class ToolResultBloatDetector:
    id = "tool_result_bloat"
    default_enabled = True

    def analyze(self, session: Session, ctx: AnalysisContext) -> list[Finding]:
        cfg = ctx.config.detectors.tool_result_bloat
        if not cfg.enabled:
            return []

        findings: list[Finding] = []
        for task in session.tasks:
            llm_calls = ordered_llm_calls(task)
            task_billed = sum(c.cost.total for c in llm_calls)
            input_rate = 0.0
            if llm_calls:
                try:
                    # rate_card_for() pins the rate card to the call's own
                    # timestamp, so a model priced through dated rate windows
                    # (Google's promo pricing) is read at the rate the call
                    # was actually billed at -- not at whichever window
                    # covers the day the analysis runs. A bare
                    # registry.get() here priced a call from a cheap promo
                    # window at the current (higher) window's rate,
                    # inflating the reported waste by the ratio between the
                    # two windows.
                    input_rate = rate_card_for(ctx.pricing.registry, llm_calls[0]).input
                except UnknownModelError:
                    input_rate = 0.0

            oversized: dict[str, list[ToolCall]] = {}
            for call in ordered_tool_calls(task):
                if call.result and len(call.result) > cfg.result_char_ceiling:
                    oversized.setdefault(call.name, []).append(call)

            for tool_name, calls in oversized.items():
                worst = max(calls, key=lambda c: len(c.result or ""))
                excess_chars = sum(len(c.result or "") - cfg.result_char_ceiling for c in calls)
                wasted_tokens = excess_chars // _CHARS_PER_TOKEN
                wasted_dollars = wasted_tokens * input_rate
                # Unconditional: a task that billed $0 (e.g. calls in a
                # published-but-rateless pricing tier) must yield $0
                # estimated waste — the cap exists precisely so an estimate
                # can never exceed real billed spend.
                wasted_dollars = min(wasted_dollars, max(task_billed, 0.0))
                worst_len = len(worst.result or "")
                high_bar = cfg.result_char_ceiling * cfg.high_severity_multiplier
                severity = Severity.high if worst_len >= high_bar else Severity.medium
                findings.append(
                    Finding(
                        id=self.id,
                        severity=severity,
                        wasted_tokens=wasted_tokens,
                        wasted_dollars=wasted_dollars,
                        basis=FindingBasis.estimated,
                        quality_risk=QualityRisk.low,
                        evidence=(
                            f"'{tool_name}' returned oversized results {len(calls)} time(s) "
                            f"in task {task.task_id} (largest: {worst_len:,} chars vs the "
                            f"{cfg.result_char_ceiling:,}-char ceiling) — oversized results "
                            "are re-fed into every later model call's context"
                        ),
                        fix=(
                            f"Truncate, paginate, or summarize '{tool_name}' output at the "
                            "tool boundary before it enters the context (e.g. head/tail a "
                            "file read, cap search results, strip boilerplate from API "
                            "responses)."
                        ),
                        span_ids=[c.span_id for c in calls],
                    )
                )
        return findings
