"""Raw spans -> typed calls (LLMCall/ToolCall/RetrievalCall), per doc §7.4/Appendix A."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from wattage.adapters.base import AdapterError
from wattage.models import LLMCall, RawSpan, RetrievalCall, TokenUsage, ToolCall


def _as_token_count(value: Any, field: str) -> int:
    """A negative token count can't come from a real provider response --
    only from a corrupted or adversarially-crafted trace -- and would
    otherwise silently subtract from total_dollars with no warning,
    exactly the "plausible-looking-but-wrong number" this project exists
    to avoid. Treated the same as any other malformed trace shape.
    """
    if value is None:
        return 0
    parsed = int(value)
    if parsed < 0:
        raise AdapterError(f"{field} cannot be negative, got {parsed}")
    return parsed


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _provider_and_model(a: dict[str, Any]) -> tuple[str, str]:
    provider = a.get("gen_ai.provider.name")
    model = a.get("gen_ai.request.model")
    if provider is None and isinstance(model, str) and "/" in model:
        # litellm's common "provider/model" convention (real-world finding
        # from any-agent's litellm-backed instrumentation, see
        # benchmarks/traces/): split it rather than reporting "unknown".
        provider, _, model = model.partition("/")
    return str(provider) if provider is not None else "unknown", str(model or "unknown")


def normalize_llm_call(span: RawSpan) -> LLMCall:
    a = span.attributes
    provider, model = _provider_and_model(a)
    usage = TokenUsage(
        input=_as_token_count(a.get("gen_ai.usage.input_tokens"), "gen_ai.usage.input_tokens"),
        output=_as_token_count(a.get("gen_ai.usage.output_tokens"), "gen_ai.usage.output_tokens"),
        cache_read=_as_token_count(
            a.get("gen_ai.usage.cache_read_input_tokens"), "gen_ai.usage.cache_read_input_tokens"
        ),
        cache_creation=_as_token_count(
            a.get("gen_ai.usage.cache_creation_input_tokens"),
            "gen_ai.usage.cache_creation_input_tokens",
        ),
        reasoning=_as_token_count(
            a.get("gen_ai.usage.reasoning_tokens"), "gen_ai.usage.reasoning_tokens"
        ),
    )
    return LLMCall(
        span_id=span.span_id,
        parent_id=span.parent_span_id,
        provider=provider,
        model=model,
        usage=usage,
        max_tokens=a.get("gen_ai.request.max_tokens"),
        reasoning_effort=a.get("gen_ai.request.reasoning_effort"),
        start_ns=span.start_ns,
        end_ns=span.end_ns,
    )


def normalize_tool_call(span: RawSpan) -> ToolCall:
    a = span.attributes
    name = str(a.get("gen_ai.tool.name", span.name))
    # "gen_ai.tool.args" / generic "gen_ai.output" are what mozilla-ai/any-agent
    # actually emits (real-trace finding, see benchmarks/traces/) alongside our
    # originally-assumed "gen_ai.tool.call.arguments"/"gen_ai.tool.call.result"
    # names — neither pair is formally standardized yet, so both are accepted.
    raw_args = a.get("gen_ai.tool.call.arguments", a.get("gen_ai.tool.args"))
    if isinstance(raw_args, str):
        try:
            raw_args = json.loads(raw_args)
        except json.JSONDecodeError:
            raw_args = None
    args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
    result_value = a.get("gen_ai.tool.call.result", a.get("gen_ai.output"))
    return ToolCall(
        span_id=span.span_id,
        parent_id=span.parent_span_id,
        name=name,
        args=args,
        args_hash=_canonical_hash(args),
        result=_stringify(result_value),
        result_hash=_canonical_hash(result_value) if result_value is not None else None,
        start_ns=span.start_ns,
        end_ns=span.end_ns,
    )


def _retrieval_chunks(a: dict[str, Any]) -> list[dict[str, Any]]:
    """`retrieval.chunks` isn't part of the GenAI semconv yet (no standard
    exists for retrieved-chunk content), so this accepts either a
    JSON-encoded string (common for exporters that flatten complex values
    into a single string attribute, same as gen_ai.tool.call.arguments) or
    an already-decoded list (a real OTLP arrayValue/kvlistValue attribute
    decodes to a native Python list before this function ever sees it).
    Plain strings in the list are wrapped as {"text": ...} for convenience;
    dicts are passed through as-is so a relevance score can ride alongside.
    """
    raw = a.get("retrieval.chunks")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    chunks: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            chunks.append(item)
        elif isinstance(item, str):
            chunks.append({"text": item})
    return chunks


def normalize_retrieval_call(span: RawSpan) -> RetrievalCall:
    a = span.attributes
    return RetrievalCall(
        span_id=span.span_id,
        parent_id=span.parent_span_id,
        query=_stringify(a.get("gen_ai.embeddings.input") or a.get("retrieval.query")),
        top_k=a.get("retrieval.top_k"),
        chunks=_retrieval_chunks(a),
        start_ns=span.start_ns,
        end_ns=span.end_ns,
    )
