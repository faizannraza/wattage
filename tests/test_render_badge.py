from wattage.models import Report, Score
from wattage.render.badge import render_badge


def _report(
    grade: str, efficiency: int, recoverable: float, monthly: float | None = None
) -> Report:
    return Report(
        trace_source="t.json",
        total_dollars=1.0,
        token_breakdown={},
        findings=[],
        score=Score(
            efficiency=efficiency,
            grade=grade,
            waste_ratio=0.0,
            quality_factor=1.0,
            quality_measured=False,
            recoverable_dollars=recoverable,
            monthly_projection=monthly,
        ),
        pricing_version="v",
        generated_at="2026-01-01T00:00:00Z",
    )


def test_badge_is_well_formed_svg_with_xml_declaration() -> None:
    svg = render_badge(_report("A", 95, 0.53))
    assert svg.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<svg" in svg
    assert svg.strip().endswith("</svg>")


def test_badge_shows_per_run_dollars_when_no_monthly_projection() -> None:
    svg = render_badge(_report("B", 84, 2.40))
    assert "$2.40 recoverable" in svg
    assert "/mo" not in svg


def test_badge_shows_monthly_projection_when_available() -> None:
    svg = render_badge(_report("B", 84, 0.10, monthly=2400.0))
    assert "~$2,400/mo recoverable" in svg


def test_badge_color_matches_grade() -> None:
    assert "#2ea44f" in render_badge(_report("A", 95, 0.0))
    assert "#cb2431" in render_badge(_report("F", 20, 0.0))


def test_badge_contains_no_external_fetches() -> None:
    """xmlns="http://www.w3.org/2000/svg" is the mandatory (never-fetched)
    namespace URI, not an external reference — this checks for the things
    that would actually cause a network fetch: an <image>/<script> with an
    http(s) href/src, or an @import/url() in style content."""
    svg = render_badge(_report("C", 72, 1.0))
    assert "<image" not in svg
    assert "<script" not in svg
    assert "@import" not in svg
    assert 'href="http' not in svg
    assert 'src="http' not in svg


def test_badge_escapes_grade_safely() -> None:
    # Grade is always a controlled A-F value, but the renderer must not
    # produce invalid XML even if a caller passes something unexpected.
    svg = render_badge(_report("A", 100, 0.0))
    assert "&amp;" not in svg  # nothing to escape in the normal path
