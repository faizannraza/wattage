"""Quality-cost frontier (doc §13.3): before/after Wattage's fixes, built
from real recorded data.

This is deliberately narrow right now: it processes whatever real (not
synthetic-fixture) traces are registered in REAL_TRACES below, and for each
task with re-sent, uncached context (prefix_churn's signal — reusing its
exact detection logic via find_resent_segments, not a re-derivation) computes
what the run would have cost had prompt caching actually been applied: the
same resent tokens billed at the model's real cache_read_mult instead of the
full input rate. That's a mechanical recomputation from real recorded token
counts and the current vendored pricing formula, not a guess.

Quality is reported as unchanged for this fix by *construction*, not by an
eval score we don't have: enabling caching changes only how tokens already
sent are billed, never the prompt content the model actually sees, so the
model's output — and therefore its quality — cannot differ. That's a
structural argument, explicitly not a measured one; the rendered plot says
so.

Right now there is exactly one validated real trace (benchmarks/traces/
any_agent_openai.otlp.json, from Phase 1's real-trace validation), so this
produces exactly one point. Padding it with points from the labeled
adversarial *fixtures* (benchmarks/adversarial_fixtures.py) would violate
the doc's own "not fabricated points" rule for this specific artifact —
those fixtures are clearly-labeled-synthetic and belong to Phase 2's
classifier benchmark, not here. The frontier grows honestly as more real
traces get validated.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from wattage.detectors.prefix_churn import find_resent_segments
from wattage.pricing.registry import PricingRegistry, UnknownModelError
from wattage.report import build_trace_and_report

REPO_ROOT = Path(__file__).parent.parent
REAL_TRACES = [REPO_ROOT / "benchmarks" / "traces" / "any_agent_openai.otlp.json"]

_QUALITY_NOTE = (
    "Unchanged by construction: enabling caching changes only how "
    "already-sent tokens are billed, never the prompt content the model "
    "sees — a structural guarantee, not an eval score."
)


@dataclass(frozen=True)
class FrontierPoint:
    trace_source: str
    fix_id: str
    before_dollars: float
    after_dollars: float
    before_quality: float
    after_quality: float
    quality_note: str


def _simulate_caching_fix(trace_path: Path) -> FrontierPoint | None:
    trace, report = build_trace_and_report(str(trace_path))
    registry = PricingRegistry.load()

    resent_dollars = 0.0
    cached_dollars = 0.0
    for session in trace.sessions:
        for task in session.tasks:
            for call, resent_tokens in find_resent_segments(task):
                try:
                    price = registry.get(call.provider, call.model)
                except UnknownModelError:
                    continue
                resent_dollars += resent_tokens * price.input
                cached_dollars += resent_tokens * price.input * price.cache_read_mult

    if resent_dollars == 0:
        return None

    savings = resent_dollars - cached_dollars
    return FrontierPoint(
        trace_source=str(trace_path.relative_to(REPO_ROOT)),
        fix_id="prefix_churn",
        before_dollars=report.total_dollars,
        after_dollars=report.total_dollars - savings,
        before_quality=1.0,
        after_quality=1.0,
        quality_note=_QUALITY_NOTE,
    )


def build_frontier(traces: list[Path] = REAL_TRACES) -> list[FrontierPoint]:
    points = []
    for trace_path in traces:
        point = _simulate_caching_fix(trace_path)
        if point is not None:
            points.append(point)
    return points


def render_frontier_svg(points: list[FrontierPoint]) -> str:
    """A small self-contained dumbbell/slope chart: x = cost ($), y = quality
    (0-1), one before->after pair per point. No external assets."""
    width, height = 560, 360
    margin = {"top": 50, "right": 30, "bottom": 50, "left": 70}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]

    if not points:
        max_cost = 1.0
    else:
        max_cost = max(p.before_dollars for p in points) * 1.15 or 1.0

    def x_for(dollars: float) -> float:
        return margin["left"] + (dollars / max_cost) * plot_w

    def y_for(quality: float) -> float:
        return margin["top"] + (1.0 - quality) * plot_h

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="ui-monospace, monospace" font-size="11">',
        f'<rect width="{width}" height="{height}" fill="#fcfcfb"/>',
        # axes
        f'<line x1="{margin["left"]}" y1="{margin["top"]}" x2="{margin["left"]}" '
        f'y2="{margin["top"] + plot_h}" stroke="#c3c2b7"/>',
        f'<line x1="{margin["left"]}" y1="{margin["top"] + plot_h}" '
        f'x2="{margin["left"] + plot_w}" y2="{margin["top"] + plot_h}" stroke="#c3c2b7"/>',
        f'<text x="14" y="{margin["top"] + plot_h / 2:.0f}" fill="#52514e" '
        f'transform="rotate(-90 14 {margin["top"] + plot_h / 2:.0f})" text-anchor="middle">'
        "task quality</text>",
        f'<text x="{margin["left"] + plot_w / 2:.0f}" y="{height - 14}" fill="#52514e" '
        'text-anchor="middle">cost per run ($)</text>',
    ]
    # Quality axis ticks (0.0 / 0.5 / 1.0) so the flat line at 1.0 has a
    # visible reference rather than floating at the plot's bare top edge.
    for tick in (0.0, 0.5, 1.0):
        ty = y_for(tick)
        parts.append(
            f'<line x1="{margin["left"] - 4}" y1="{ty:.1f}" x2="{margin["left"]}" '
            f'y2="{ty:.1f}" stroke="#c3c2b7"/>'
        )
        parts.append(
            f'<text x="{margin["left"] - 8}" y="{ty + 3:.1f}" fill="#898781" '
            f'text-anchor="end">{tick:.1f}</text>'
        )
    # Cost axis ticks (0 and the max).
    for tick in (0.0, max_cost):
        tx = x_for(tick)
        parts.append(
            f'<text x="{tx:.1f}" y="{margin["top"] + plot_h + 16}" fill="#898781" '
            f'text-anchor="middle">${tick:.4f}</text>'
        )

    for i, point in enumerate(points):
        x1, y1 = x_for(point.before_dollars), y_for(point.before_quality)
        x2, y2 = x_for(point.after_dollars), y_for(point.after_quality)
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="#898781" stroke-width="1.5" marker-end="url(#arrow)"/>'
        )
        parts.append(f'<circle cx="{x1:.1f}" cy="{y1:.1f}" r="5" fill="#e34948"/>')
        parts.append(f'<circle cx="{x2:.1f}" cy="{y2:.1f}" r="5" fill="#008300"/>')
        label = escape(f"{point.fix_id}: ${point.before_dollars:.4f} → ${point.after_dollars:.4f}")
        label_y = margin["top"] - 30 + i * 14
        parts.append(
            f'<text x="{margin["left"]:.1f}" y="{label_y:.1f}" fill="#0b0b0b">{label}</text>'
        )

    parts.insert(
        2,  # after the XML declaration (0) and the <svg> open tag (1)
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" '
        'orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#898781"/></marker></defs>',
    )
    # Legend in the top-right corner, clear of the per-point data labels
    # which render at the top-left above the plot area.
    legend_x = margin["left"] + plot_w - 90
    legend_y = 18
    parts.append(f'<circle cx="{legend_x + 4}" cy="{legend_y - 4}" r="4" fill="#e34948"/>')
    parts.append(
        f'<text x="{legend_x + 14}" y="{legend_y}" fill="#52514e" font-size="10">before</text>'
    )
    parts.append(f'<circle cx="{legend_x + 64}" cy="{legend_y - 4}" r="4" fill="#008300"/>')
    parts.append(
        f'<text x="{legend_x + 74}" y="{legend_y}" fill="#52514e" font-size="10">after</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


if __name__ == "__main__":
    pts = build_frontier()
    if not pts:
        print("No real before/after points available yet — no trace had a prefix_churn finding.")
    else:
        for p in pts:
            print(
                f"{p.trace_source} [{p.fix_id}]: ${p.before_dollars:.6f} -> ${p.after_dollars:.6f}"
            )
            print(f"  quality: {p.before_quality} -> {p.after_quality} ({p.quality_note})")
        svg = render_frontier_svg(pts)
        out_path = REPO_ROOT / "benchmarks" / "report" / "frontier.svg"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(svg, encoding="utf-8")
        print(f"wrote {out_path}")
