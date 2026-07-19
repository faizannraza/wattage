# reasoning_overspend

**Detects:** a call spending heavily on internal reasoning/thinking tokens for what looks like a simple step.

## How it works

Reasoning tokens are billed at the output rate — often the most expensive per-token class a model offers. A call is flagged when its reasoning tokens exceed a configured ceiling (500 by default) *and* its own final output is small, the same "simple step" signal `model_mismatch` uses.

Like [`verbosity`](verbosity.md), there's no way to know "how much reasoning was actually necessary" without judging the content — that would need the optional LLM judge, off by default. So this uses the same honest, configured-ceiling policy: reasoning tokens beyond the ceiling are counted as excess, which is a policy estimate against a threshold you control, not a factual claim about what was strictly required.

## Fix

Lower `reasoning_effort` (or disable extended thinking) for this specific step.

## Quality risk: review

Reducing reasoning effort is grouped with model downgrades as needing quality evidence before it counts toward your score — but unlike `model_mismatch`, this detector doesn't require a `--quality` map to produce a finding in the first place. Lowering reasoning effort is a smaller, more easily reversible change than swapping the whole model, so it's surfaced by default; the score-gating protection (findings tagged `review` never count toward the grade unless quality is measured) is what keeps this honest, not a detector-level silence-by-default rule.
