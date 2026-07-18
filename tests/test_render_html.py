"""Golden/smoke test for the HTML flame graph (doc §3.6): renders without
error on a real trace, and is scanned for zero external http(s):// fetches
— the self-contained requirement, verified rather than assumed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from wattage.render.html import render_html
from wattage.report import build_trace_and_report

REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture
def real_trace_html() -> str:
    trace, report = build_trace_and_report(
        str(REPO_ROOT / "benchmarks" / "traces" / "any_agent_openai.otlp.json")
    )
    return render_html(trace, report)


def test_renders_without_error_and_looks_like_a_full_page(real_trace_html: str) -> None:
    assert real_trace_html.startswith("<!DOCTYPE html>")
    assert real_trace_html.strip().endswith("</html>")
    assert "<svg" in real_trace_html


def test_contains_the_real_trace_source_and_score(real_trace_html: str) -> None:
    assert "any_agent_openai.otlp.json" in real_trace_html
    assert "prefix_churn" in real_trace_html  # the one real finding on this trace


def test_no_findings_case_renders_a_friendly_message() -> None:
    trace, report = build_trace_and_report(str(REPO_ROOT / "examples" / "sample_trace.json"))
    html = render_html(trace, report)
    assert "No findings" in html


# Every href/src that could trigger a network fetch, plus @import and script
# loading — deliberately excludes the mandatory (never-fetched) SVG/XML
# namespace URIs like xmlns="http://www.w3.org/2000/svg".
_EXTERNAL_FETCH_PATTERNS = [
    re.compile(r'\bsrc\s*=\s*"https?://'),
    re.compile(r'\bhref\s*=\s*"https?://'),
    re.compile(r"@import\s"),
    re.compile(r"<link\b"),
    re.compile(r"<script\b[^>]*\bsrc\s*="),
    re.compile(r"\bfetch\s*\("),
    re.compile(r"XMLHttpRequest"),
]


def test_self_contained_no_external_network_fetches(real_trace_html: str) -> None:
    for pattern in _EXTERNAL_FETCH_PATTERNS:
        assert not pattern.search(real_trace_html), f"found forbidden pattern: {pattern.pattern}"

    # The only "http://" occurrences allowed at all are the mandatory,
    # never-fetched XML/SVG namespace URI — as an xmlns attribute, or as the
    # JS string passed to document.createElementNS (same URI, same reason).
    for line in real_trace_html.splitlines():
        if "http://" in line or "https://" in line:
            is_namespace_uri = "xmlns=" in line or "svgNS = " in line
            assert is_namespace_uri, f"unexpected external reference: {line.strip()}"
