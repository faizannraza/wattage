"""SVG badge renderer (doc §6.4): the README badge — free passive
distribution every adopting repo advertises.

Self-contained (inline styles, no external font/CDN loading) so it renders
identically wherever it's embedded. Text width is estimated per character
(a fixed average advance width) rather than measured — there's no real text
layout engine available outside a browser, which is what every static
badge generator does.

Shows "~$X/mo recoverable" only when Score.monthly_projection is actually
populated (it isn't yet — see report.py's own note on why extrapolating
from one trace's wall-clock duration would be dishonest); otherwise shows
the per-run recoverable-dollars figure, never a fabricated monthly claim.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from wattage.models import Report, Score

_GRADE_COLORS = {
    "A": "#2ea44f",
    "B": "#57ab5a",
    "C": "#dbab09",
    "D": "#e36209",
    "F": "#cb2431",
}
_LABEL_BG = "#555555"
_CHAR_WIDTH = 6.5
_PADDING = 10
_HEIGHT = 20


def _text_width(text: str) -> float:
    return len(text) * _CHAR_WIDTH + _PADDING * 2


def _dollar_headline(score: Score) -> str:
    if score.monthly_projection is not None:
        return f"~${score.monthly_projection:,.0f}/mo recoverable"
    return f"${score.recoverable_dollars:,.2f} recoverable"


def render_badge(report: Report) -> str:
    score = report.score
    label = escape("⚡ Token Efficiency")
    value = escape(f"{score.grade} ({score.efficiency}) · {_dollar_headline(score)}")

    label_width = _text_width(label)
    value_width = _text_width(value)
    total_width = label_width + value_width
    color = _GRADE_COLORS.get(score.grade, _GRADE_COLORS["F"])

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_width:.0f}" '
        f'height="{_HEIGHT}" role="img" aria-label="{label}: {value}">\n'
        f"  <title>{label}: {value}</title>\n"
        '  <linearGradient id="s" x2="0" y2="100%">\n'
        '    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>\n'
        '    <stop offset="1" stop-opacity=".1"/>\n'
        "  </linearGradient>\n"
        '  <clipPath id="r">\n'
        f'    <rect width="{total_width:.0f}" height="{_HEIGHT}" rx="3" fill="#fff"/>\n'
        "  </clipPath>\n"
        '  <g clip-path="url(#r)">\n'
        f'    <rect width="{label_width:.0f}" height="{_HEIGHT}" fill="{_LABEL_BG}"/>\n'
        f'    <rect x="{label_width:.0f}" width="{value_width:.0f}" height="{_HEIGHT}" '
        f'fill="{color}"/>\n'
        f'    <rect width="{total_width:.0f}" height="{_HEIGHT}" fill="url(#s)"/>\n'
        "  </g>\n"
        '  <g fill="#fff" text-anchor="middle" '
        'font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">\n'
        f'    <text x="{label_width / 2:.0f}" y="14">{label}</text>\n'
        f'    <text x="{label_width + value_width / 2:.0f}" y="14">{value}</text>\n'
        "  </g>\n"
        "</svg>\n"
    )
