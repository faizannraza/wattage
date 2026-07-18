"""prefix_churn (doc §4.1): re-sent context not being cached.

Per task, walks LLM calls in chronological order. Without message content
capture we can't diff prompts directly, so this uses the token-count proxy
the doc allows as a fallback: if a call's input tokens are at least as large
as the *entire* prior call's context (input+output) and no cache read
happened on this call, that prior context was almost certainly re-sent
verbatim and billed at full input price. The monotonic-growth guard
(curr.input >= prior_total) is what keeps this from flagging a genuinely
different/shrunk prefix.

Known limitation: two coincidentally same-sized-but-different prefixes can't
be told apart from token counts alone — that needs message capture or a
prompt fingerprint (see LLMCall.prompt_fingerprint), which isn't populated
yet. Left as a documented future enhancement rather than faked here.
"""

from __future__ import annotations

from wattage.detectors.base import AnalysisContext, ordered_llm_calls
from wattage.models import Finding, QualityRisk, Session, Severity
from wattage.pricing.registry import UnknownModelError


class PrefixChurnDetector:
    id = "prefix_churn"
    default_enabled = True

    def analyze(self, session: Session, ctx: AnalysisContext) -> list[Finding]:
        cfg = ctx.config.detectors.prefix_churn
        findings: list[Finding] = []

        for task in session.tasks:
            calls = ordered_llm_calls(task)
            if len(calls) < 2:
                continue

            resent_tokens = 0
            resent_dollars = 0.0
            span_ids: list[str] = []

            for prev, curr in zip(calls, calls[1:], strict=False):
                if curr.usage.cache_read > 0:
                    continue  # caching is active for this turn; not churn
                prior_total = prev.usage.input + prev.usage.output
                if prior_total <= 0 or curr.usage.input < prior_total:
                    continue  # prefix shrank or changed; not a simple resend

                try:
                    price = ctx.pricing.registry.get(curr.provider, curr.model)
                except UnknownModelError:
                    continue

                resent_tokens += prior_total
                resent_dollars += prior_total * price.input
                span_ids.append(curr.span_id)

            if resent_tokens == 0:
                continue

            task_dollars = sum(c.cost.total for c in calls)
            ratio = resent_dollars / task_dollars if task_dollars > 0 else 0.0
            severity = Severity.high if ratio >= cfg.high_severity_ratio else Severity.medium

            findings.append(
                Finding(
                    id=self.id,
                    severity=severity,
                    wasted_tokens=resent_tokens,
                    wasted_dollars=resent_dollars,
                    quality_risk=QualityRisk.none,
                    evidence=(
                        f"{resent_tokens} tokens of prior context re-sent uncached across "
                        f"{len(span_ids)} turn(s) in task {task.task_id} "
                        f"({ratio:.0%} of task cost)"
                    ),
                    fix=(
                        "Enable prompt caching on the stable prefix (system prompt + tool "
                        "schemas); move volatile content to the tail of the prompt."
                    ),
                    span_ids=span_ids,
                )
            )

        return findings
