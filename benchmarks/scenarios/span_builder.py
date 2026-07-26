"""Shared OTLP JSON span-construction helpers for the large real-world
scenario traces in this directory. Produces the exact wire shape
src/wattage/adapters/otlp_file.py reads (resourceSpans[].scopeSpans[].spans[],
attributes as key/value list, gen_ai.* attribute names), verified against
that source directly, not guessed.
"""

from __future__ import annotations

import json


def _kv(key, value):
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": str(value)}}


def chat_span(
    span_id,
    parent_id,
    trace_id,
    start_ns,
    duration_ns,
    provider,
    model,
    input_tokens,
    output_tokens,
    reasoning_tokens=0,
    cache_read=0,
    cache_creation=0,
    max_tokens=None,
    name=None,
):
    attrs = {
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": provider,
        "gen_ai.request.model": model,
        "gen_ai.usage.input_tokens": input_tokens,
        "gen_ai.usage.output_tokens": output_tokens,
    }
    if reasoning_tokens:
        attrs["gen_ai.usage.reasoning_tokens"] = reasoning_tokens
    if cache_read:
        attrs["gen_ai.usage.cache_read_input_tokens"] = cache_read
    if cache_creation:
        attrs["gen_ai.usage.cache_creation_input_tokens"] = cache_creation
    if max_tokens is not None:
        attrs["gen_ai.request.max_tokens"] = max_tokens
    return {
        "spanId": span_id,
        "parentSpanId": parent_id or "",
        "traceId": trace_id,
        "name": name or f"chat {model}",
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(start_ns + duration_ns),
        "attributes": [_kv(k, v) for k, v in attrs.items()],
    }


def tool_span(span_id, parent_id, trace_id, start_ns, duration_ns, tool_name, args, result):
    attrs = {
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.tool.name": tool_name,
        "gen_ai.tool.call.arguments": json.dumps(args, sort_keys=True),
        "gen_ai.tool.call.result": result,
    }
    return {
        "spanId": span_id,
        "parentSpanId": parent_id or "",
        "traceId": trace_id,
        "name": f"execute_tool {tool_name}",
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(start_ns + duration_ns),
        "attributes": [_kv(k, v) for k, v in attrs.items()],
    }


def agent_span(span_id, parent_id, trace_id, start_ns, duration_ns, agent_name):
    attrs = {"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": agent_name}
    return {
        "spanId": span_id,
        "parentSpanId": parent_id or "",
        "traceId": trace_id,
        "name": f"invoke_agent {agent_name}",
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(start_ns + duration_ns),
        "attributes": [_kv(k, v) for k, v in attrs.items()],
    }


def embeddings_span(span_id, parent_id, trace_id, start_ns, duration_ns, query, chunk_texts):
    """A genuine SpanKind.embeddings span, with chunk content carried in a
    retrieval.chunks attribute (normalize.py's normalize_retrieval_call
    reads this into RetrievalCall.chunks -- see finding1_isolated_test.py,
    which used exactly this span shape to catch the real gap where that
    wasn't true yet)."""
    attrs = {
        "gen_ai.operation.name": "embeddings",
        "gen_ai.embeddings.input": query,
        "retrieval.chunks": json.dumps(chunk_texts),
    }
    return {
        "spanId": span_id,
        "parentSpanId": parent_id or "",
        "traceId": trace_id,
        "name": "embeddings",
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(start_ns + duration_ns),
        "attributes": [_kv(k, v) for k, v in attrs.items()],
    }


def wrap_otlp_json(spans, service_name="test-agent"):
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [_kv("service.name", service_name)]},
                "scopeSpans": [{"scope": {"name": service_name}, "spans": spans}],
            }
        ]
    }
