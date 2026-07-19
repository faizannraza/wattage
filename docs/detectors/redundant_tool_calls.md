# redundant_tool_calls

**Detects:** the same (or near-identical) tool call executed more than once with the same effective result, within a short window.

## How it works

Each tool call's arguments are canonicalized (recursively sorted keys, and — in "fuzzy" mode, the default — floats rounded to 2 decimal places so near-identical numeric args collapse to the same key) and hashed alongside the tool name. A sliding window (5 calls by default) looks back for a matching key.

Two guards keep this honest:

- **Result-changed guard.** If the tool's own observed result differs between the two calls, they weren't actually redundant — a polling call whose status genuinely changed is never flagged, even if its args are identical.
- **Exempt list.** Tools on the exempt list (`poll_status`, `wait`, `healthcheck` by default) are excluded entirely — never flagged, never even considered as a match candidate for another call.

Fuzzy matching specifically targets the case exact-hash duplicate detectors miss: a retry loop that includes a slightly different value each time (an incrementing attempt counter, a fresh timestamp) never hashes equal, even though it's the same call in every way that matters.

## Cost estimate

Tool calls don't carry a priced `Cost` the way LLM calls do, so the wasted-dollar estimate comes from the duplicate call's captured result text, using the same rough ~4-characters-per-token conversion the industry commonly uses (the same approximation Anthropic's own pricing FAQ cites). When no result content was captured, the finding is still reported — it's real and actionable — but the dollar figure is honestly left at zero rather than invented.

## Fix

Memoize or cache this tool's result within the task, or debounce repeated calls at the call site.

## Quality risk: none

Removing a genuinely redundant call (same effective result) can't change the agent's final output.
