"""Raw spans -> typed calls (LLMCall/ToolCall/RetrievalCall), per doc §7.4/Appendix A.

TokenUsage.output is always the *visible* (non-reasoning) portion, and
TokenUsage.reasoning is tracked separately -- confirmed against real
provider docs, not assumed: both OpenAI's completion_tokens_details.
reasoning_tokens and Anthropic's output_tokens_details.thinking_tokens
report reasoning as a subset already included in the provider's raw
output_tokens count, not an additional charge on top of it. This module
does that split once, here, so every downstream consumer (pricing,
token_breakdown, detectors) can just add usage.output + usage.reasoning
without re-deriving or double-billing it.

Cache tokens (cache_read/cache_creation) get the *same* subset treatment,
but only for providers confirmed to report input_tokens inclusive of them
-- unlike reasoning, real providers disagree here: OpenAI's prompt_tokens
includes cached_tokens as a subset (same convention as reasoning), but
Anthropic's API reports input_tokens/cache_creation_input_tokens/
cache_read_input_tokens as three genuinely separate, additive fields (both
confirmed against each provider's own docs). See _INCLUSIVE_CACHE_PROVIDERS
below.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import ValidationError

from wattage.adapters.base import AdapterError
from wattage.models import LLMCall, RawSpan, RetrievalCall, TokenUsage, ToolCall


def _as_token_count(value: Any, field: str) -> int:
    """A negative or non-numeric token count can't come from a real
    provider response -- only from a corrupted or adversarially-crafted
    trace -- and a negative one would otherwise silently subtract from
    total_dollars with no warning, exactly the "plausible-looking-but-wrong
    number" this project exists to avoid. Treated the same as any other
    malformed trace shape.
    """
    if value is None:
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise AdapterError(f"{field} must be an integer, got {value!r}") from exc
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


# Providers whose real API response is confirmed to report raw
# input_tokens *inclusive* of cache tokens -- currently just OpenAI
# (prompt_tokens includes cached_tokens, confirmed against OpenAI's own
# docs). Every other provider (anthropic, mistral, unknown) keeps the
# existing disjoint/additive treatment, matching Anthropic's confirmed
# real API shape and this project's existing pricing formula, which
# already prices cache_read/cache_creation as separate additive amounts.
_INCLUSIVE_CACHE_PROVIDERS = frozenset({"openai"})


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

    raw_output = _as_token_count(a.get("gen_ai.usage.output_tokens"), "gen_ai.usage.output_tokens")
    reasoning = _as_token_count(
        a.get("gen_ai.usage.reasoning.output_tokens"), "gen_ai.usage.reasoning.output_tokens"
    )
    if reasoning > raw_output:
        # Per the OTel GenAI semconv registry, reasoning.output_tokens
        # "SHOULD be included in gen_ai.usage.output_tokens" -- both
        # OpenAI and Anthropic bill reasoning/thinking tokens as part of
        # output_tokens, with the reasoning attribute reporting a subset
        # for breakdown, not an extra amount on top. Reasoning exceeding
        # the reported output total is therefore not a real usage shape.
        raise AdapterError(
            f"gen_ai.usage.reasoning.output_tokens ({reasoning}) exceeds "
            f"gen_ai.usage.output_tokens ({raw_output}) -- reasoning tokens must be a "
            "subset of output tokens"
        )

    raw_input = _as_token_count(a.get("gen_ai.usage.input_tokens"), "gen_ai.usage.input_tokens")
    cache_read = _as_token_count(
        a.get("gen_ai.usage.cache_read.input_tokens"), "gen_ai.usage.cache_read.input_tokens"
    )
    cache_creation = _as_token_count(
        a.get("gen_ai.usage.cache_creation.input_tokens"),
        "gen_ai.usage.cache_creation.input_tokens",
    )
    if provider in _INCLUSIVE_CACHE_PROVIDERS:
        if cache_read + cache_creation > raw_input:
            raise AdapterError(
                f"gen_ai.usage.cache_read.input_tokens + cache_creation.input_tokens "
                f"({cache_read + cache_creation}) exceeds gen_ai.usage.input_tokens "
                f"({raw_input}) for provider {provider!r} -- cache tokens must be a "
                "subset of input tokens for this provider"
            )
        visible_input = raw_input - cache_read - cache_creation
    else:
        visible_input = raw_input

    usage = TokenUsage(
        input=visible_input,
        # Visible (non-reasoning) output only -- reasoning is billed at the
        # same output rate but tracked as its own TokenUsage field, so
        # subtracting it here keeps the two additive without double-billing
        # what the provider already counted once inside raw_output.
        output=raw_output - reasoning,
        cache_read=cache_read,
        cache_creation=cache_creation,
        reasoning=reasoning,
    )
    try:
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
    except ValidationError as exc:
        raise AdapterError(f"malformed chat call attributes: {exc}") from exc


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
