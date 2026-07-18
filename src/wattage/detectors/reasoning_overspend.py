"""reasoning_overspend (doc §4.8): excess reasoning/thinking tokens where a
lower effort would likely have sufficed.

Like verbosity.py, there's no ground truth for "how much reasoning was
actually necessary" without judging the content, so this uses the same
configured-ceiling policy: reasoning tokens beyond `expected_reasoning_
ceiling` on a call whose own final output is small (the "simple step, heavy
internal reasoning" archetype) are counted as excess. This is a policy
estimate, not a factual claim.

quality_risk is "review" (doc §6.3 groups reasoning reduction with model
downgrades) — protected by the score's existing review-risk gating (it
never counts toward the efficiency grade unless quality is measured),
rather than a detector-level require_quality_map like model_mismatch's:
lowering reasoning effort is a smaller, more reversible change than
swapping models.
"""

from __future__ import annotations

from wattage.detectors.base import AnalysisContext, ordered_llm_calls
from wattage.models import Finding, QualityRisk, Session, Severity
from wattage.pricing.registry import UnknownModelError


class ReasoningOverspendDetector:
    id = "reasoning_overspend"
    default_enabled = True

    def analyze(self, session: Session, ctx: AnalysisContext) -> list[Finding]:
        cfg = ctx.config.detectors.reasoning_overspend
        if not cfg.enabled:
            return []

        findings: list[Finding] = []
        for task in session.tasks:
            for call in ordered_llm_calls(task):
                if call.usage.reasoning <= cfg.expected_reasoning_ceiling:
                    continue
                if call.usage.output > cfg.simple_output_ceiling:
                    continue  # a large final output suggests genuinely complex work

                try:
                    price = ctx.pricing.registry.get(call.provider, call.model)
                except UnknownModelError:
                    continue

                excess = call.usage.reasoning - cfg.expected_reasoning_ceiling
                wasted_dollars = excess * price.output  # reasoning billed at output rate
                severity = (
                    Severity.high
                    if call.usage.reasoning >= cfg.expected_reasoning_ceiling * 3
                    else Severity.medium
                )

                findings.append(
                    Finding(
                        id=self.id,
                        severity=severity,
                        wasted_tokens=excess,
                        wasted_dollars=wasted_dollars,
                        quality_risk=QualityRisk.review,
                        evidence=(
                            f"{call.usage.reasoning} reasoning tokens on a step with only "
                            f"{call.usage.output} output tokens (configured expected "
                            f"ceiling: {cfg.expected_reasoning_ceiling})"
                        ),
                        fix="Lower reasoning_effort (or disable extended thinking) for this step.",
                        span_ids=[call.span_id],
                    )
                )

        return findings
