# model_mismatch

**Detects:** a premium model used for a step that's really just picking a tool — a step a cheaper model would very likely handle equally well.

Public routing guidance suggests 60–70% of agent calls suit a smaller model; this detector looks for the clearest, most defensible slice of that: calls whose whole job was a short, structured tool-selection decision.

## How it works

A call is a downgrade candidate when its iteration produced a tool call (its job was picking a tool, not open-ended reasoning) *and* its own output is small (150 tokens or fewer by default) — the "tool-only step, short structured output" archetype. There's no task-type classifier in this codebase, so this narrow structural signal is the only "clearly trivial step" indicator available without guessing at intent.

**By default, this detector produces nothing at all without evidence.** `require_quality_map` defaults to `true`: recommending a model swap is consequential enough that the project's own design treats "no evidence the cheaper model actually works here" as a reason to stay silent, not merely to caveat the finding. Supply a `--quality quality.json` with a `downgrade_evals` entry (`"tool_select@<candidate-model>": {"pass_rate": 0.97}`) showing the candidate model passes at or above the configured threshold, and the detector starts reporting real, dollar-quantified findings.

## Fix

Route this specific step to the configured cheaper candidate model (`claude-haiku-4-5` for Anthropic, `gpt-5.6-luna` for OpenAI, by default — configurable per provider).

## Quality risk: review

A model downgrade is one of the two waste patterns the project's own scoring rules explicitly single out as needing evidence before it can count toward your Token Efficiency score — the other is `reasoning_overspend`.
