"""Golden/smoke test for the HTML flame graph (doc §3.6): renders without
error on a real trace, and is scanned for zero external http(s):// fetches
— the self-contained requirement, verified rather than assumed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from wattage.config import WattageConfig
from wattage.detectors.base import AnalysisContext
from wattage.detectors.redundant_tool_calls import RedundantToolCallsDetector
from wattage.models import Iteration, Loop, Report, Score, Session, Task, ToolCall, Trace
from wattage.pricing.engine import PricingEngine
from wattage.pricing.registry import PricingRegistry
from wattage.render.html import render_html
from wattage.report import build_trace_and_report

REPO_ROOT = Path(__file__).parent.parent


def _unpriced_report(unpriced_calls: int, unpriced_models: list[str]) -> Report:
    return Report(
        trace_source="t.json",
        total_dollars=0.0,
        token_breakdown={},
        findings=[],
        score=Score(
            efficiency=100,
            grade="A",
            waste_ratio=0.0,
            quality_factor=1.0,
            quality_measured=False,
            recoverable_dollars=0.0,
        ),
        pricing_version="v",
        generated_at="2026-01-01T00:00:00Z",
        unpriced_calls=unpriced_calls,
        unpriced_models=unpriced_models,
    )


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


def test_unpriced_trace_shows_a_banner_and_not_a_letter_grade_chip() -> None:
    """A grade computed from an incomplete cost figure must never render as
    a normal-looking letter grade -- this is a shareable HTML report,
    exactly the kind of artifact someone might screenshot or forward
    without reading every line."""
    report = _unpriced_report(1, ["openai/gpt-4o"])
    html = render_html(Trace(source="t.json", sessions=[]), report)

    assert '<div class="unpriced-banner">' in html
    assert "openai/gpt-4o" in html
    assert 'class="score-chip unpriced"' in html
    assert "A (100)" not in html
    assert "No findings on the priced portion" in html


def test_trace_content_cannot_break_out_of_the_script_block() -> None:
    """The real bug this closes: flame-graph node names (tool names, model
    strings, retrieval queries) come straight from trace content -- and
    anyone can hand `wattage report --html` an arbitrary trace file. A tool
    name of "</script><script>...", embedded via bare json.dumps() into
    `const DATA = ...`, closed the legitimate <script> tag early and let
    the rest execute as a new, attacker-controlled <script> in this
    self-contained, often-opened-in-a-browser HTML report -- a stored XSS.
    """
    payload = "</script><script>alert(document.cookie)</script>"
    tool = ToolCall(span_id="sp1", name=payload, result="x")
    iteration = Iteration(index=0, tool_calls=[tool])
    loop = Loop(loop_id="loop1", iterations=[iteration])
    task = Task(task_id="task1", loops=[loop])
    session = Session(session_id="s1", tasks=[task])
    trace = Trace(source="src", sessions=[session])
    report = _unpriced_report(0, [])

    html = render_html(trace, report)

    assert "</script><script>" not in html
    start = html.find("const DATA = ") + len("const DATA = ")
    end = html.find(";\n", start)
    data = json.loads(html[start:end])

    def find_tool_name(node: dict) -> str | None:
        if node.get("kind") == "tool":
            return node["name"]  # type: ignore[no-any-return]
        for child in node.get("children", []):
            found = find_tool_name(child)
            if found is not None:
                return found
        return None

    assert find_tool_name(data) == payload


def test_trace_content_containing_a_placeholder_token_is_not_reexpanded() -> None:
    """The real bug this closes: render_html did sequential str.replace()
    calls against one growing string, substituting __FINDINGS_HTML__ before
    __TREE_JSON__. A finding's evidence text can legitimately contain the
    literal text "__TREE_JSON__" (e.g. a tool actually named that), and the
    later __TREE_JSON__ replacement would re-match that already-inserted
    text, leaking the entire serialized tree JSON blob into the findings
    sidebar. A single regex pass over the static template (this test's
    fix) never rescans already-substituted content, so this can't happen
    regardless of what a placeholder-named tool call's evidence contains.
    """
    tool_a = ToolCall(span_id="sp1", name="__TREE_JSON__", result="x" * 40)
    tool_b = ToolCall(span_id="sp2", name="__TREE_JSON__", result="x" * 40)
    iteration_a = Iteration(index=0, tool_calls=[tool_a])
    iteration_b = Iteration(index=1, tool_calls=[tool_b])
    loop = Loop(loop_id="loop1", iterations=[iteration_a, iteration_b])
    task = Task(task_id="task1", loops=[loop])
    session = Session(session_id="s1", tasks=[task])
    trace = Trace(source="src", sessions=[session])
    report = _unpriced_report(0, [])

    ctx = AnalysisContext(pricing=PricingEngine(PricingRegistry.load()), config=WattageConfig())
    report.findings = RedundantToolCallsDetector().analyze(session, ctx)
    assert report.findings  # sanity: the detector actually fired

    html = render_html(trace, report)

    evidence_start = html.find('<div class="evidence">')
    evidence_end = html.find("</div>", evidence_start)
    evidence_div = html[evidence_start:evidence_end]
    assert "kind" not in evidence_div  # the leaked tree JSON would contain this
    assert "__TREE_JSON__" in evidence_div  # the real tool name, shown as itself


def test_fully_priced_trace_has_no_unpriced_banner() -> None:
    trace, report = build_trace_and_report(str(REPO_ROOT / "examples" / "sample_trace.json"))
    html = render_html(trace, report)
    assert '<div class="unpriced-banner">' not in html
    assert 'class="score-chip">' in html  # no stray trailing space in the class attribute


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
