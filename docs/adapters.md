# Adapters

An adapter turns a trace source into the stream of spans Wattage normalizes into calls, iterations, loops, tasks, and sessions. The only adapter shipped today is the **OTLP JSON file adapter** — deterministic, offline, and testable, which is why the project's own build required it to work end-to-end before anything else.

## OTLP file adapter

Point `wattage report` (or any other command) at a `.json` file in the standard [OTLP JSON](https://opentelemetry.io/docs/specs/otlp/) wire format — the `resourceSpans[].scopeSpans[].spans[]` shape any OTel exporter or collector produces. Wattage reads the [GenAI semantic-convention attributes](https://opentelemetry.io/docs/specs/semconv/gen-ai/) (`gen_ai.request.model`, `gen_ai.usage.input_tokens`, and so on) off each span.

## Real-world naming tolerance

The GenAI semantic conventions are still evolving, and different frameworks that predate or diverge from the current spec use different attribute and operation names for the same thing. Wattage's real-trace validation (against a genuine [mozilla-ai/any-agent](https://github.com/mozilla-ai/any-agent) trace, not a synthetic fixture) surfaced three concrete gaps, all now handled:

- **`call_llm` as an operation name.** The canonical operation name for a chat completion span is `chat`, but some instrumentation (any-agent's, for one) emits `call_llm` instead. Wattage recognizes both.
- **litellm-style `"provider/model"` strings.** Frameworks that route through [litellm](https://github.com/BerriAI/litellm) often report a single `gen_ai.request.model` value like `"mistral/mistral-small-latest"` with no separate provider attribute. Wattage splits on the first `/` when no explicit provider is given.
- **Legacy model attribute names.** Pre-semconv instrumentation used `llm.model` or `openai.model` instead of `gen_ai.request.model`. Wattage maps these onto the canonical name.
- **Tool call attribute variants.** Neither `gen_ai.tool.call.arguments`/`gen_ai.tool.call.result` nor any-agent's `gen_ai.tool.args`/generic `gen_ai.output` are formally standardized yet, so both pairs are accepted.

None of these were added speculatively — each was found by actually running Wattage against a real trace and fixing what broke, not by guessing at what *might* break. See `benchmarks/traces/README.md` in the repository for the full provenance of that validation trace.

## Pricing

Wattage never fabricates a price. It ships a vendored, versioned pricing snapshot (`src/wattage/pricing/data/pricing.yaml`) sourced directly from each provider's own pricing page, with the fetch date recorded. If a call uses a model with no registry entry, Wattage warns and leaves that call's cost at zero rather than guessing a rate — and `wattage ci` treats any unpriced call as a hard pricing error (exit code 4), because a cost-regression gate built on an undercount isn't trustworthy.

You can override or extend the registry with your own `pricing.yaml` via `--pricing`, useful for negotiated enterprise rates or self-hosted models.

## What's next

Adapters for OpenLLMetry (traceloop) and OpenInference (Arize) native export formats, plus a live OTLP endpoint/collector adapter and a live-tail streaming mode, are on the roadmap — the normalized data model (sessions → tasks → loops → iterations → calls) doesn't change; only the ingestion layer does.
