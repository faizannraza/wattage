import json
from pathlib import Path

import pytest

from wattage.adapters.base import AdapterError
from wattage.adapters.otlp_file import OTLPFileAdapter
from wattage.models import SpanKind


def _write_otlp(tmp_path: Path, spans: list[dict]) -> Path:
    payload = {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(payload))
    return path


def test_supports_only_json_paths() -> None:
    adapter = OTLPFileAdapter()
    assert adapter.supports("trace.json") is True
    assert adapter.supports("trace.otlp.json") is True
    assert adapter.supports("trace.pb") is False


def test_reads_canonical_gen_ai_attributes(tmp_path: Path) -> None:
    path = _write_otlp(
        tmp_path,
        [
            {
                "traceId": "t1",
                "spanId": "s1",
                "parentSpanId": "",
                "name": "chat claude-sonnet-4-6",
                "startTimeUnixNano": "1000",
                "endTimeUnixNano": "2000",
                "attributes": [
                    {"key": "gen_ai.provider.name", "value": {"stringValue": "anthropic"}},
                    {"key": "gen_ai.request.model", "value": {"stringValue": "claude-sonnet-4-6"}},
                    {"key": "gen_ai.usage.input_tokens", "value": {"intValue": "18450"}},
                    {"key": "gen_ai.usage.output_tokens", "value": {"intValue": "320"}},
                ],
            }
        ],
    )
    spans = list(OTLPFileAdapter().read(str(path)))
    assert len(spans) == 1
    span = spans[0]
    assert span.span_id == "s1"
    assert span.parent_span_id is None
    assert span.kind == SpanKind.chat
    assert span.attributes["gen_ai.request.model"] == "claude-sonnet-4-6"
    assert span.attributes["gen_ai.usage.input_tokens"] == 18450
    assert span.start_ns == 1000
    assert span.end_ns == 2000


def test_legacy_model_attribute_names_map_to_canonical(tmp_path: Path) -> None:
    path = _write_otlp(
        tmp_path,
        [
            {
                "traceId": "t1",
                "spanId": "s-legacy-llm",
                "name": "chat",
                "attributes": [{"key": "llm.model", "value": {"stringValue": "claude-legacy"}}],
            },
            {
                "traceId": "t1",
                "spanId": "s-legacy-openai",
                "name": "chat",
                "attributes": [{"key": "openai.model", "value": {"stringValue": "gpt-4o-legacy"}}],
            },
        ],
    )
    spans = {s.span_id: s for s in OTLPFileAdapter().read(str(path))}
    assert spans["s-legacy-llm"].attributes["gen_ai.request.model"] == "claude-legacy"
    assert spans["s-legacy-openai"].attributes["gen_ai.request.model"] == "gpt-4o-legacy"


def test_canonical_model_attribute_wins_over_legacy(tmp_path: Path) -> None:
    path = _write_otlp(
        tmp_path,
        [
            {
                "traceId": "t1",
                "spanId": "s1",
                "name": "chat",
                "attributes": [
                    {"key": "llm.model", "value": {"stringValue": "should-not-be-used"}},
                    {"key": "gen_ai.request.model", "value": {"stringValue": "claude-sonnet-4-6"}},
                ],
            }
        ],
    )
    spans = list(OTLPFileAdapter().read(str(path)))
    assert spans[0].attributes["gen_ai.request.model"] == "claude-sonnet-4-6"


def test_classifies_kind_from_span_name_when_operation_attribute_absent(tmp_path: Path) -> None:
    path = _write_otlp(
        tmp_path,
        [{"traceId": "t1", "spanId": "s1", "name": "execute_tool search_docs", "attributes": []}],
    )
    spans = list(OTLPFileAdapter().read(str(path)))
    assert spans[0].kind == SpanKind.execute_tool


def test_span_missing_span_id_raises_adapter_error_not_a_bare_key_error(tmp_path: Path) -> None:
    """The real bug this closes: a span missing 'spanId' used to raise a
    bare KeyError straight out of the adapter, which `wattage ci` didn't
    catch -- it fell through as an uncaught exception (Python's default
    exit code 1), indistinguishable from exit code 1's real meaning ("a
    fail-on threshold breached"), instead of the documented exit code 3
    ("ingestion error"). AdapterError is what ci.py now catches."""
    path = _write_otlp(tmp_path, [{"traceId": "t1", "name": "chat", "attributes": []}])
    with pytest.raises(AdapterError, match="spanId"):
        list(OTLPFileAdapter().read(str(path)))


def test_non_dict_span_entry_raises_adapter_error(tmp_path: Path) -> None:
    payload = {"resourceSpans": [{"scopeSpans": [{"spans": "not-a-list-of-objects"}]}]}
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(AdapterError):
        list(OTLPFileAdapter().read(str(path)))


def test_non_object_top_level_json_raises_adapter_error(tmp_path: Path) -> None:
    path = tmp_path / "trace.json"
    path.write_text(json.dumps([1, 2, 3]))
    with pytest.raises(AdapterError, match="top-level JSON must be an object"):
        list(OTLPFileAdapter().read(str(path)))
