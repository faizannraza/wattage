"""Raw spans -> typed calls (LLMCall/ToolCall/RetrievalCall), per doc §7.4/Appendix A."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from wattage.models import LLMCall, RawSpan, RetrievalCall, TokenUsage, ToolCall


def _as_int(value: Any) -> int:
    return int(value) if value is not None else 0


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_llm_call(span: RawSpan) -> LLMCall:
    a = span.attributes
    usage = TokenUsage(
        input=_as_int(a.get("gen_ai.usage.input_tokens")),
        output=_as_int(a.get("gen_ai.usage.output_tokens")),
        cache_read=_as_int(a.get("gen_ai.usage.cache_read_input_tokens")),
        cache_creation=_as_int(a.get("gen_ai.usage.cache_creation_input_tokens")),
        reasoning=_as_int(a.get("gen_ai.usage.reasoning_tokens")),
    )
    return LLMCall(
        span_id=span.span_id,
        parent_id=span.parent_span_id,
        provider=str(a.get("gen_ai.provider.name", "unknown")),
        model=str(a.get("gen_ai.request.model", "unknown")),
        usage=usage,
        max_tokens=a.get("gen_ai.request.max_tokens"),
        reasoning_effort=a.get("gen_ai.request.reasoning_effort"),
        start_ns=span.start_ns,
        end_ns=span.end_ns,
    )


def normalize_tool_call(span: RawSpan) -> ToolCall:
    a = span.attributes
    name = str(a.get("gen_ai.tool.name", span.name))
    raw_args = a.get("gen_ai.tool.call.arguments")
    args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
    return ToolCall(
        span_id=span.span_id,
        parent_id=span.parent_span_id,
        name=name,
        args=args,
        args_hash=_canonical_hash(args),
        result=_stringify(a.get("gen_ai.tool.call.result")),
        result_hash=_canonical_hash(a["gen_ai.tool.call.result"])
        if "gen_ai.tool.call.result" in a
        else None,
        start_ns=span.start_ns,
        end_ns=span.end_ns,
    )


def normalize_retrieval_call(span: RawSpan) -> RetrievalCall:
    a = span.attributes
    return RetrievalCall(
        span_id=span.span_id,
        parent_id=span.parent_span_id,
        query=_stringify(a.get("gen_ai.embeddings.input") or a.get("retrieval.query")),
        top_k=a.get("retrieval.top_k"),
        start_ns=span.start_ns,
        end_ns=span.end_ns,
    )
