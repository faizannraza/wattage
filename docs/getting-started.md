# Getting your first trace

Every Wattage command needs one input: an [OTLP JSON](https://opentelemetry.io/docs/specs/otlp/)
trace containing [GenAI semantic-convention](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
(`gen_ai.*`) span attributes. Which path below applies depends on what you
already have.

## You already have OTel GenAI traces

If your agent framework or observability tool (an OTel Collector, OpenLLMetry,
or anything else that speaks the GenAI semantic conventions) already exports
OTLP JSON, you're done — point Wattage at that export directly:

```bash
uvx wattage report your_trace.json
```

Check its docs for an "OTLP export," "OTel Collector integration," or "file
exporter" option — see [Adapters](adapters.md) for exactly which attribute
names and operation-name variants Wattage tolerates, since not every tool
uses the canonical semconv names yet.

## You have zero instrumentation

Wrap one real LLM call in a real OpenTelemetry span, then export it. This is
the actual minimum — three attributes and the two token counts your
provider's SDK already returns with its response:

```python
# examples/instrument_minimal.py in this repo has the full, runnable version
with tracer.start_as_current_span("chat claude-sonnet-4-6") as span:
    span.set_attribute("gen_ai.operation.name", "chat")
    span.set_attribute("gen_ai.provider.name", "anthropic")
    span.set_attribute("gen_ai.request.model", "claude-sonnet-4-6")
    # ... your real API call here ...
    span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
```

Run the complete version end to end:

```bash
pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-common
python examples/instrument_minimal.py   # writes trace.json
wattage report trace.json
```

That produces a real `trace.json` — encoded via OpenTelemetry's own official
OTLP JSON encoder, not an approximation of the format — and a real, correctly
priced report:

```
╭──── ⚡ wattage — trace.json ────╮
│ Token Efficiency: A (100)   Total cost: $0.0087 │
│ quality: unmeasured                             │
╰─────────────────────────────────────────────────╯
      Token breakdown
┏━━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ Category       ┃ Tokens ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ input          │   1200 │
│ output         │    340 │
│ cache_read     │      0 │
│ cache_creation │      0 │
│ reasoning      │      0 │
└────────────────┴────────┘
No findings — this trace looks efficient.
pricing: 2026-07-18-verified
```

From here, replace the stand-in call in the script with your actual agent's
LLM calls (wrap each one in its own span), add a `tool` span with
`gen_ai.operation.name: "execute_tool"` for any tool calls, and you have a
real trace of your own agent for Wattage's detectors — including the
convergence engine, which needs multiple iterations of tool activity to have
anything to analyze. `docs/detectors/index.md` and `convergence.md` cover
what each detector looks for once you're past this first trace.

## Just want to see it work first?

No instrumentation needed at all — the repo ships a ready-made fixture:

```bash
git clone https://github.com/faizannraza/wattage
cd wattage && uv sync
uv run wattage report examples/sample_trace.json
```
