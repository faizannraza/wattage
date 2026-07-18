# Real-trace fixtures

## `any_agent_openai.otlp.json`

A genuine (not fabricated or hand-written) agent trace, converted to OTLP
JSON wire format from
[mozilla-ai/any-agent](https://github.com/mozilla-ai/any-agent)'s
`docs/traces/OPENAI_trace.json` (Apache-2.0). any-agent's own docs describe
this file as captured from actually running their integration test suite
against a live model (`mistral/mistral-small-latest`) — a real 3-turn
tool-using agent loop (`get_current_time` → `write_file` → final answer),
not a documentation-only example.

`any_agent_openai_source.json` is the untouched original download.
`convert_any_agent_trace.py` re-encodes it into the OTLP wire shape our
`OTLPFileAdapter` reads (attributes as a key/value array, nano timestamps as
strings, etc.) — every span name, attribute, token count, and timestamp is
carried over verbatim; nothing about the trace's substance was changed.

Running `wattage report` against this trace was Phase 1's real-trace
validation gate and surfaced three genuine gaps our synthetic fixtures
hadn't exercised, all fixed in the adapter/normalizer/registry rather than
by altering the trace:

1. any-agent emits `gen_ai.operation.name: "call_llm"` for chat spans, not
   the canonical `"chat"` — added as a recognized alias.
2. Its `gen_ai.request.model` is a litellm-style `"provider/model"` string
   with no separate `gen_ai.provider.name` — the normalizer now splits it.
3. Its tool spans use `gen_ai.tool.args` / generic `gen_ai.output` rather
   than our originally-assumed `gen_ai.tool.call.arguments` /
   `gen_ai.tool.call.result` — neither pair is formally standardized yet, so
   both are now accepted.
4. Mistral wasn't in the vendored pricing registry at all — added with
   current verified pricing (see `pricing/data/pricing.yaml`).

Note: the trace's own embedded `gen_ai.usage.input_cost`/`output_cost`
attributes reflect whatever Mistral charged when it was recorded
(2025-09-16, at the then-current Mistral Small 3 rate of $0.10/$0.30 per
MTok). Wattage always prices against the *current* vendored registry
(Mistral Small 4, $0.15/$0.60 per MTok as of 2026-07-18) rather than
replaying a historical rate — so Wattage's `total_dollars` legitimately
differs from the trace's own cost fields. That's intentional, not a bug.

## Result (Phase 1 exit gate)

`wattage report benchmarks/traces/any_agent_openai.otlp.json --json`
produces exactly one finding: `prefix_churn`, correctly identifying that
this agent re-sends its growing conversation context on every turn with no
caching in effect (true of this trace — a plain 3-turn tool loop with no
`cache_control` anywhere). The other three detectors correctly stay silent:
no duplicate tool calls (the two tool calls are different tools), no
verbose output (max 46 output tokens), no cache writes to under-redeem.
Pinned as a regression test in `tests/test_real_trace_any_agent.py`.
