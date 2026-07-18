"""model_mismatch (doc §4.7): a premium model used for a step a cheaper
model would handle equally well.

The step-complexity heuristic here is deliberately narrow and structural:
an LLM call whose iteration produced a tool call (its job was picking a
tool, not open-ended reasoning) and whose own output is small — the doc's
"tool-only steps, short structured outputs" archetype. There's no
task-type classifier in this codebase (the same limitation verbosity.py
notes), so this is the only "clearly trivial step" signal available
without guessing.

quality_risk is always "review". By default (require_quality_map=True,
doc's own config default) this detector produces *nothing at all* unless a
--quality map's downgrade_evals confirms the candidate model actually
passes for this step role at or above min_downgrade_pass_rate —
recommending a model swap is consequential enough that the doc treats "no
evidence" as a reason to stay silent, not just to caveat the finding.

wasted_tokens here means "tokens billed at the wrong (premium) rate," not
"tokens that need not have been spent" (the tokens themselves are
necessary; the waste is the per-token price differential) — a different
sense than most other detectors, worth noting when reading a report.
"""

from __future__ import annotations

from wattage.config import ModelMismatchConfig
from wattage.detectors.base import AnalysisContext
from wattage.models import Finding, LLMCall, QualityRisk, Session, Severity
from wattage.pricing.registry import UnknownModelError
from wattage.scoring.quality import downgrade_pass_rate

_STEP_ROLE = "tool_select"


class ModelMismatchDetector:
    id = "model_mismatch"
    default_enabled = True

    def analyze(self, session: Session, ctx: AnalysisContext) -> list[Finding]:
        cfg = ctx.config.detectors.model_mismatch
        if not cfg.enabled:
            return []
        findings: list[Finding] = []
        for task in session.tasks:
            for loop in task.loops:
                for iteration in loop.iterations:
                    if not iteration.tool_calls:
                        continue  # not a tool-selection step
                    for call in iteration.llm_calls:
                        finding = self._check_call(call, cfg, ctx)
                        if finding is not None:
                            findings.append(finding)
        return findings

    def _check_call(
        self, call: LLMCall, cfg: ModelMismatchConfig, ctx: AnalysisContext
    ) -> Finding | None:
        if call.usage.output > cfg.simple_output_ceiling:
            return None

        candidate_model = cfg.downgrade_candidates.get(call.provider)
        if candidate_model is None or candidate_model == call.model:
            return None

        try:
            price = ctx.pricing.registry.get(call.provider, call.model)
            candidate_price = ctx.pricing.registry.get(call.provider, candidate_model)
        except UnknownModelError:
            return None

        if candidate_price.input >= price.input:
            return None  # candidate isn't actually cheaper

        pass_rate = downgrade_pass_rate(ctx.quality_map, _STEP_ROLE, candidate_model)
        if cfg.require_quality_map and (
            pass_rate is None or pass_rate < cfg.min_downgrade_pass_rate
        ):
            return None

        wasted_dollars = call.usage.input * (price.input - candidate_price.input) + (
            call.usage.output * (price.output - candidate_price.output)
        )
        if wasted_dollars <= 0:
            return None

        input_savings_ratio = (price.input - candidate_price.input) / price.input
        severity = Severity.high if input_savings_ratio >= 0.5 else Severity.medium

        evidence = (
            f"{call.model} used for a tool-selection step ({call.usage.output} output "
            f"tokens) that {candidate_model} could likely handle"
        )
        if pass_rate is not None:
            evidence += f" (confirmed pass rate {pass_rate:.0%})"

        return Finding(
            id=self.id,
            severity=severity,
            wasted_tokens=call.usage.input + call.usage.output,
            wasted_dollars=wasted_dollars,
            quality_risk=QualityRisk.review,
            evidence=evidence,
            fix=f"Route this step to {candidate_model}.",
            span_ids=[call.span_id],
        )
