"""Minimal OTel GenAI instrumentation -> a trace.json Wattage can read.

For anyone with zero existing OpenTelemetry instrumentation: wraps one LLM
call in a real OpenTelemetry span using the GenAI semantic-convention
attributes (gen_ai.*), then exports the real span batch to the standard
OTLP JSON wire format via OTel's own official encoder -- not a
hand-approximated format. See docs/getting-started.md for the full
walkthrough.

If you already have OTel GenAI traces (Langfuse, Helicone, an OTel
Collector, OpenLLMetry, ...), you don't need this at all -- just point
`wattage report` at whatever OTLP JSON export they already produce.

Run:
    pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-common
    python instrument_minimal.py
    wattage report trace.json
"""

from __future__ import annotations

import json
import time

from google.protobuf.json_format import MessageToDict
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult


class _CaptureExporter(SpanExporter):
    """Collects finished spans in memory instead of sending them anywhere --
    swap this for a real opentelemetry-exporter-otlp-proto-http exporter (or
    an OTel Collector) once your agent has somewhere real to send traces."""

    def __init__(self) -> None:
        self.spans: list = []

    def export(self, spans):
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


def main() -> None:
    exporter = _CaptureExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "my-agent"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("my-agent")

    # Replace this block with your actual LLM call. The three things Wattage
    # needs are: gen_ai.operation.name="chat", gen_ai.request.model, and the
    # two usage.*_tokens counts your provider's SDK returns with its response.
    with tracer.start_as_current_span("chat claude-sonnet-4-6") as span:
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.provider.name", "anthropic")
        span.set_attribute("gen_ai.request.model", "claude-sonnet-4-6")
        # --- stand-in for your real API call ---
        time.sleep(0.01)
        input_tokens, output_tokens = 1200, 340  # from your provider's response.usage
        # ----------------------------------------
        span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", output_tokens)

    request = encode_spans(exporter.spans)
    with open("trace.json", "w", encoding="utf-8") as f:
        json.dump(MessageToDict(request), f, indent=2)

    print("wrote trace.json -- now run: wattage report trace.json")


if __name__ == "__main__":
    main()
