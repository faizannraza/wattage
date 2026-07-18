"""Primary v1 adapter: OTLP JSON export (file or stream) -> RawSpans.

Deterministic and offline, which is why the doc makes this the only adapter
required for the Phase 0 exit gate.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import IO, Any

from wattage.adapters.base import Adapter
from wattage.models import RawSpan, SpanKind

# gen_ai.* is the canonical attribute namespace (OTel GenAI semconv). Older
# instrumentation (pre-semconv OpenInference/traceloop spans) used these
# names instead; map them onto the canonical key so downstream code only
# ever has to look in one place.
_LEGACY_MODEL_KEYS = ("llm.model", "openai.model")

_KIND_BY_OPERATION = {
    "chat": SpanKind.chat,
    # "call_llm" isn't a canonical semconv operation name, but it's what
    # mozilla-ai/any-agent (a real, actively maintained multi-framework
    # instrumentation) actually emits — found via real-trace validation, not
    # speculatively added.
    "call_llm": SpanKind.chat,
    "execute_tool": SpanKind.execute_tool,
    "invoke_agent": SpanKind.invoke_agent,
    "create_agent": SpanKind.create_agent,
    "embeddings": SpanKind.embeddings,
}


def _decode_value(value: dict[str, Any]) -> Any:
    """Decode one OTLP JSON AnyValue (protobuf JSON mapping: int64 etc. as strings)."""
    if "stringValue" in value:
        return value["stringValue"]
    if "intValue" in value:
        return int(value["intValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "boolValue" in value:
        return bool(value["boolValue"])
    if "arrayValue" in value:
        return [_decode_value(v) for v in value["arrayValue"].get("values", [])]
    if "kvlistValue" in value:
        return _decode_attributes(value["kvlistValue"].get("values", []))
    if "bytesValue" in value:
        return value["bytesValue"]
    return None


def _decode_attributes(raw_attrs: list[dict[str, Any]]) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    for kv in raw_attrs:
        key = kv.get("key")
        if key is None:
            continue
        attrs[key] = _decode_value(kv.get("value", {}))
    return attrs


def _apply_legacy_aliases(attrs: dict[str, Any]) -> dict[str, Any]:
    if "gen_ai.request.model" not in attrs:
        for legacy_key in _LEGACY_MODEL_KEYS:
            if legacy_key in attrs:
                attrs["gen_ai.request.model"] = attrs[legacy_key]
                break
    return attrs


def _classify_kind(attrs: dict[str, Any], span_name: str) -> SpanKind:
    operation = attrs.get("gen_ai.operation.name")
    if isinstance(operation, str) and operation in _KIND_BY_OPERATION:
        return _KIND_BY_OPERATION[operation]
    # Span display names follow "{operation} {model}" (semconv naming rule);
    # fall back to the leading token when gen_ai.operation.name is absent.
    leading = span_name.split(" ", 1)[0]
    return _KIND_BY_OPERATION.get(leading, SpanKind.other)


class OTLPFileAdapter(Adapter):
    def supports(self, source: str) -> bool:
        return isinstance(source, str) and source.endswith((".json", ".otlp.json"))

    def read(self, source: str | IO[str]) -> Iterable[RawSpan]:
        payload = self._load(source)
        for resource_span in payload.get("resourceSpans", []):
            for scope_span in resource_span.get("scopeSpans", []):
                for span in scope_span.get("spans", []):
                    yield self._to_raw_span(span)

    @staticmethod
    def _load(source: str | IO[str]) -> dict[str, Any]:
        if isinstance(source, str):
            with open(source, encoding="utf-8") as f:
                return dict(json.load(f))
        return dict(json.load(source))

    @staticmethod
    def _to_raw_span(span: dict[str, Any]) -> RawSpan:
        attrs = _apply_legacy_aliases(_decode_attributes(span.get("attributes", [])))
        events = [
            {
                "name": event.get("name", ""),
                "attributes": _decode_attributes(event.get("attributes", [])),
            }
            for event in span.get("events", [])
        ]
        name = span.get("name", "")
        return RawSpan(
            span_id=span["spanId"],
            parent_span_id=span.get("parentSpanId") or None,
            trace_id=span.get("traceId"),
            name=name,
            kind=_classify_kind(attrs, name),
            attributes=attrs,
            start_ns=int(span.get("startTimeUnixNano", 0)),
            end_ns=int(span.get("endTimeUnixNano", 0)),
            events=events,
        )
