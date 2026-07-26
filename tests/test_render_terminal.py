import io

from rich.console import Console

from wattage.models import Report, Score
from wattage.render.terminal import render_terminal


def _report(total_dollars: float) -> Report:
    return Report(
        trace_source="t.json",
        total_dollars=total_dollars,
        token_breakdown={
            "input": 10,
            "output": 5,
            "cache_read": 0,
            "cache_creation": 0,
            "reasoning": 0,
        },
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
    )


def _render(report: Report) -> str:
    buf = io.StringIO()
    console = Console(file=buf, width=100, no_color=True, force_terminal=False)
    render_terminal(report, console=console)
    return buf.getvalue()


def test_total_cost_never_shows_a_misleading_zero_for_a_real_sub_cent_amount() -> None:
    """The real bug this closes: the headline hardcoded `:.4f` for total
    cost, so a genuinely nonzero but very small total (a real, tiny trace
    priced with a cheap model) printed as a literal "Total cost: $0.0000"
    -- indistinguishable from a trace that cost nothing at all."""
    output = _render(_report(0.000015))
    assert "Total cost: $0.0000 " not in output
    assert "Total cost: $0.0000\n" not in output
    assert "$0.000015" in output


def test_total_cost_renders_normally_for_a_regular_amount() -> None:
    output = _render(_report(0.0602))
    assert "$0.0602" in output
