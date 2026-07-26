from wattage.models import RawSpan, SpanKind
from wattage.normalize import normalize_retrieval_call


def _span(attributes: dict) -> RawSpan:
    return RawSpan(span_id="s0", name="embeddings", kind=SpanKind.embeddings, attributes=attributes)


def test_chunks_populated_from_json_encoded_string_of_plain_text() -> None:
    """A JSON-encoded string is the common shape for exporters that flatten
    complex attribute values into one string (same pattern already used for
    gen_ai.tool.call.arguments)."""
    span = _span({"retrieval.chunks": '["chunk one text", "chunk two text"]'})
    call = normalize_retrieval_call(span)
    assert call.chunks == [{"text": "chunk one text"}, {"text": "chunk two text"}]


def test_chunks_populated_from_json_encoded_string_of_dicts_with_relevance() -> None:
    span = _span({"retrieval.chunks": '[{"text": "a", "relevance_score": 0.9}, {"text": "b"}]'})
    call = normalize_retrieval_call(span)
    assert call.chunks == [{"text": "a", "relevance_score": 0.9}, {"text": "b"}]


def test_chunks_populated_from_already_decoded_list() -> None:
    """A real OTLP arrayValue/kvlistValue attribute decodes to a native
    Python list before normalize.py ever sees it (see
    adapters/otlp_file.py's _decode_value) -- must work without a JSON
    round-trip too."""
    span = _span({"retrieval.chunks": [{"text": "already a dict"}, "already a string"]})
    call = normalize_retrieval_call(span)
    assert call.chunks == [{"text": "already a dict"}, {"text": "already a string"}]


def test_chunks_defaults_to_empty_list_when_attribute_absent() -> None:
    call = normalize_retrieval_call(_span({}))
    assert call.chunks == []


def test_chunks_is_empty_not_a_crash_on_malformed_json() -> None:
    call = normalize_retrieval_call(_span({"retrieval.chunks": "not valid json["}))
    assert call.chunks == []


def test_chunks_ignores_non_list_non_dict_junk_entries() -> None:
    span = _span({"retrieval.chunks": '["ok text", 42, null, {"text": "also ok"}]'})
    call = normalize_retrieval_call(span)
    assert call.chunks == [{"text": "ok text"}, {"text": "also ok"}]
