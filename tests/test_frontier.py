"""Tests for the quality-cost frontier (doc §13.3, plan 3.5): every number
must come from the real any-agent trace's actual recorded tokens and the
current vendored pricing formula — hand-verified below, not asserted from
whatever the code currently outputs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.frontier import build_frontier, render_frontier_svg

REPO_ROOT = Path(__file__).parent.parent
REAL_TRACE = REPO_ROOT / "benchmarks" / "traces" / "any_agent_openai.otlp.json"


def test_real_trace_yields_exactly_one_point() -> None:
    points = build_frontier([REAL_TRACE])
    assert len(points) == 1


def test_point_matches_hand_computed_before_after_dollars() -> None:
    points = build_frontier([REAL_TRACE])
    point = points[0]

    # From prefix_churn's own finding on this trace (see test_real_trace_any_agent.py):
    # 658 resent tokens at mistral-small-latest's input rate (0.15e-6), cache_read_mult 0.10.
    resent_tokens = 658
    input_rate = 0.15e-6
    cache_read_mult = 0.10
    resent_dollars = resent_tokens * input_rate
    cached_dollars = resent_tokens * input_rate * cache_read_mult
    savings = resent_dollars - cached_dollars

    assert point.before_dollars == pytest.approx(0.0001986, abs=1e-7)
    assert point.after_dollars == pytest.approx(point.before_dollars - savings, abs=1e-9)
    assert point.after_dollars < point.before_dollars


def test_quality_is_reported_unchanged_with_an_honest_structural_note() -> None:
    point = build_frontier([REAL_TRACE])[0]
    assert point.before_quality == 1.0
    assert point.after_quality == 1.0
    assert "structural" in point.quality_note.lower()
    assert "not" in point.quality_note.lower()  # "not an eval score"


def test_trace_with_no_prefix_churn_finding_yields_no_point() -> None:
    sample = REPO_ROOT / "examples" / "sample_trace.json"
    assert build_frontier([sample]) == []


def test_svg_renders_with_no_external_references() -> None:
    points = build_frontier([REAL_TRACE])
    svg = render_frontier_svg(points)
    assert svg.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<svg" in svg
    assert "http://www.w3.org/2000/svg" in svg  # the one allowed namespace URI
    for line in svg.splitlines():
        if "http://" in line or "https://" in line:
            assert "xmlns=" in line


def test_svg_handles_the_empty_case_without_crashing() -> None:
    svg = render_frontier_svg([])
    assert "<svg" in svg
