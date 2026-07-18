"""redundant_tool_calls (doc §4.5): the same or near-identical tool call
executed multiple times with the same effective result within a short
window.

Args are canonicalized (recursively sorted keys, and — when `fuzzy` is on —
floats rounded to 2 decimal places so near-identical numeric args collapse
to the same key) then hashed per tool name. A sliding window looks back for
a matching key; a result-hash mismatch (the tool's own observed result
differs) means it wasn't actually redundant — e.g. a polling call with a
changing status — so it's never flagged even if the args match. Tools on
the exempt list (poll_status, wait, healthcheck by default) are excluded
entirely: never flagged, never used as a match candidate.

Token/dollar cost is estimated from the duplicate call's captured result
text using the ~4-characters-per-token approximation (the same rough
industry conversion Anthropic's own pricing FAQ cites), priced at the
task's first LLM call's input rate, since a redundant tool result mainly
wastes tokens by being re-fed into a subsequent model call's context. When
no result content was captured, the finding is still reported (it's real
and actionable) but wasted_tokens/wasted_dollars are honestly left at 0
rather than invented.
"""

from __future__ import annotations

import json
from collections import deque
from typing import Any

from wattage.detectors.base import AnalysisContext, ordered_llm_calls, ordered_tool_calls
from wattage.models import Finding, QualityRisk, Session, Severity, Task, ToolCall
from wattage.pricing.registry import ModelPrice, UnknownModelError

_CHARS_PER_TOKEN = 4


def _round_floats(value: Any, ndigits: int) -> Any:
    if isinstance(value, float):
        return round(value, ndigits)
    if isinstance(value, dict):
        return {k: _round_floats(v, ndigits) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_round_floats(v, ndigits) for v in value]
    return value


def _fuzzy_key(call: ToolCall, fuzzy: bool) -> str:
    args = _round_floats(call.args, 2) if fuzzy else call.args
    canonical = json.dumps(args, sort_keys=True, default=str)
    return f"{call.name}:{canonical}"


def _representative_price(task: Task, ctx: AnalysisContext) -> ModelPrice | None:
    calls = ordered_llm_calls(task)
    if not calls:
        return None
    first = calls[0]
    try:
        return ctx.pricing.registry.get(first.provider, first.model)
    except UnknownModelError:
        return None


class RedundantToolCallsDetector:
    id = "redundant_tool_calls"
    default_enabled = True

    def analyze(self, session: Session, ctx: AnalysisContext) -> list[Finding]:
        cfg = ctx.config.detectors.redundant_tool_calls
        findings: list[Finding] = []

        for task in session.tasks:
            calls = ordered_tool_calls(task)
            if not calls:
                continue
            price = _representative_price(task, ctx)

            window: deque[tuple[str, ToolCall]] = deque(maxlen=cfg.window)
            for call in calls:
                if call.name in cfg.exempt_tools:
                    continue  # excluded entirely: never flagged, never a match candidate

                key = _fuzzy_key(call, cfg.fuzzy)
                match = next((prior for prior_key, prior in window if prior_key == key), None)
                window.append((key, call))

                if match is None:
                    continue
                if (
                    match.result_hash is not None
                    and call.result_hash is not None
                    and match.result_hash != call.result_hash
                ):
                    continue  # result changed; not actually redundant (e.g. polling)

                estimated_tokens = len(call.result) // _CHARS_PER_TOKEN if call.result else 0
                wasted_dollars = estimated_tokens * price.input if price is not None else 0.0

                findings.append(
                    Finding(
                        id=self.id,
                        severity=Severity.medium,
                        wasted_tokens=estimated_tokens,
                        wasted_dollars=wasted_dollars,
                        quality_risk=QualityRisk.none,
                        evidence=(
                            f"'{call.name}' called again with equivalent args "
                            f"(span {match.span_id} -> {call.span_id}) in task {task.task_id}"
                        ),
                        fix=(
                            "Memoize/cache this tool's result within the task, "
                            "or debounce repeated calls."
                        ),
                        span_ids=[match.span_id, call.span_id],
                    )
                )

        return findings
