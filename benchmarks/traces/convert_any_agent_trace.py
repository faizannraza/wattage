"""One-time conversion of a real any-agent trace into OTLP JSON wire format.

Source: https://github.com/mozilla-ai/any-agent/blob/main/docs/traces/OPENAI_trace.json
(Apache-2.0). any-agent's own docs describe this file as a real trace
captured from running their integration test suite against a live model
(mistral/mistral-small-latest) — not a hand-written or documentation-only
example. It's exported in the OpenTelemetry Python SDK's own span-dump shape
(a flat "spans" list with big-int trace/span ids and unix-nano timestamps as
ints), not the OTLP wire envelope (resourceSpans/scopeSpans/spans with
attributes as a key/value array and nano timestamps as strings) our
OTLPFileAdapter reads. This script re-encodes the wire *shape* only —
every span name, attribute, token count, and timestamp is carried over
verbatim; nothing about the trace's substance is changed.

Run once: `python benchmarks/traces/convert_any_agent_trace.py`
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SOURCE = Path(__file__).parent / "any_agent_openai_source.json"
DEST = Path(__file__).parent / "any_agent_openai.otlp.json"


def _to_any_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    return {"stringValue": str(value)}


def _to_otlp_attributes(attributes: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"key": k, "value": _to_any_value(v)} for k, v in attributes.items()]


def convert(raw: dict[str, Any]) -> dict[str, Any]:
    spans = []
    for span in raw["spans"]:
        parent_span_id = span["parent"]["span_id"] if span["parent"] else None
        spans.append(
            {
                "traceId": str(span["context"]["trace_id"]),
                "spanId": str(span["context"]["span_id"]),
                "parentSpanId": str(parent_span_id) if parent_span_id is not None else "",
                "name": span["name"],
                "startTimeUnixNano": str(span["start_time"]),
                "endTimeUnixNano": str(span["end_time"]),
                "attributes": _to_otlp_attributes(span["attributes"]),
            }
        )
    return {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}


if __name__ == "__main__":
    raw = json.loads(SOURCE.read_text())
    converted = convert(raw)
    DEST.write_text(json.dumps(converted, indent=2))
    print(f"wrote {DEST} ({len(converted['resourceSpans'][0]['scopeSpans'][0]['spans'])} spans)")
