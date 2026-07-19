# prefix_churn

**Detects:** a large, stable prefix (system prompt, tool schemas, conversation history) being re-sent and re-billed at full price on every turn, instead of being cached.

This is the single highest-leverage fix in most agent bills — independent audits have found re-sent context accounts for roughly 60% of a typical agent's spend, and it's usually just a missing configuration flag away from being fixed.

## How it works

Wattage doesn't require message content capture to catch this. For each pair of consecutive LLM calls in a task, if:

1. the later call has **no cache read** (caching isn't in effect for this turn), and
2. its input token count is **at least as large as the entire prior call's context** (input + output),

...then that prior context was almost certainly re-sent verbatim. The monotonic-growth check in condition 2 is what keeps this from flagging a genuinely different or shrunk prefix — a prompt that got smaller or changed shape between turns isn't churn.

## Known limitation

Two coincidentally same-sized-but-different prefixes can't be told apart from token counts alone. Telling them apart for certain needs message content or a prompt fingerprint, which most production traces don't capture (for privacy and payload-size reasons). This is a documented gap, not a silently-accepted inaccuracy — the guard above is specifically designed to keep the false-positive rate low even without content.

## Fix

Enable prompt caching on the stable prefix (system prompt + tool schemas), and move any volatile content (timestamps, request IDs) to the *end* of the prompt, after the cache breakpoint.

## Quality risk: none

Caching changes only how already-sent tokens are billed — never the prompt content the model actually sees. There's no way for this fix to change the model's output.
