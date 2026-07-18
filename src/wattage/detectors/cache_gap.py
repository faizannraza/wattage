"""cache_gap (doc §4.2): caching is attempted but under-redeemed by reads.

Distinct from prefix_churn (caching never attempted at all): this only fires
when cache_creation > 0 somewhere in the task. It measures how much of the
write premium (cache writes cost more than plain input, on the assumption
future reads will redeem it) went unredeemed by later reads.

Known limitation: "prefix below the provider's minimum cacheable size" is
also a documented root cause in the doc, but it's indistinguishable from
"caching never enabled" using token counts alone — both produce
cache_creation == cache_read == 0. Detecting it would need the request's
cache_control attribute (not part of the OTel GenAI usage attributes we
read), so it's left for a future adapter enhancement rather than guessed at.
"""

from __future__ import annotations

from wattage.detectors.base import AnalysisContext, ordered_llm_calls
from wattage.models import Finding, QualityRisk, Session, Severity
from wattage.pricing.registry import UnknownModelError


class CacheGapDetector:
    id = "cache_gap"
    default_enabled = True

    def analyze(self, session: Session, ctx: AnalysisContext) -> list[Finding]:
        findings: list[Finding] = []

        for task in session.tasks:
            calls = ordered_llm_calls(task)
            total_creation = sum(c.usage.cache_creation for c in calls)
            total_read = sum(c.usage.cache_read for c in calls)
            if total_creation == 0:
                continue  # no caching attempted at all here; prefix_churn's territory

            # A write is "redeemed" once total reads catch up to total writes;
            # below that, the unredeemed fraction of every write was pure premium.
            redemption_ratio = min(1.0, total_read / total_creation) if total_read > 0 else 0.0
            unredeemed_fraction = 1.0 - redemption_ratio
            if unredeemed_fraction <= 0:
                continue

            wasted_tokens = 0
            wasted_dollars = 0.0
            span_ids: list[str] = []
            for call in calls:
                if call.usage.cache_creation <= 0:
                    continue
                try:
                    price = ctx.pricing.registry.get(call.provider, call.model)
                except UnknownModelError:
                    continue
                premium_per_token = price.input * max(price.cache_write_mult - 1.0, 0.0)
                if premium_per_token <= 0:
                    continue
                wasted_dollars += (
                    call.usage.cache_creation * premium_per_token * unredeemed_fraction
                )
                wasted_tokens += int(call.usage.cache_creation * unredeemed_fraction)
                span_ids.append(call.span_id)

            if wasted_dollars <= 0:
                continue

            severity = Severity.high if total_read == 0 else Severity.medium
            findings.append(
                Finding(
                    id=self.id,
                    severity=severity,
                    wasted_tokens=wasted_tokens,
                    wasted_dollars=wasted_dollars,
                    quality_risk=QualityRisk.none,
                    evidence=(
                        f"{total_creation} cache-write tokens vs {total_read} cache-read tokens "
                        f"in task {task.task_id} ({unredeemed_fraction:.0%} of the write premium "
                        "unredeemed)"
                    ),
                    fix=(
                        "Move volatile fields after the cache breakpoint, raise the cache TTL, "
                        "or drop cache_control if this content genuinely won't be re-read."
                    ),
                    span_ids=span_ids,
                )
            )

        return findings
