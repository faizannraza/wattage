import pytest

from wattage.models import Finding, QualityRisk, Severity
from wattage.scoring.quality import compute_quality_factor
from wattage.scoring.score import compute_score, grade_for


def _finding(dollars: float, quality_risk: QualityRisk = QualityRisk.none) -> Finding:
    return Finding(
        id="test",
        severity=Severity.medium,
        wasted_dollars=dollars,
        quality_risk=quality_risk,
        evidence="e",
        fix="f",
    )


@pytest.mark.parametrize(
    "efficiency,expected_grade",
    [
        (100, "A"),
        (90, "A"),
        (89, "B"),
        (80, "B"),
        (79, "C"),
        (70, "C"),
        (69, "D"),
        (60, "D"),
        (59, "F"),
        (0, "F"),
    ],
)
def test_grade_bands(efficiency: int, expected_grade: str) -> None:
    assert grade_for(efficiency) == expected_grade


def test_no_findings_yields_perfect_score() -> None:
    score = compute_score(findings=[], total_dollars=10.0)
    assert score.efficiency == 100
    assert score.grade == "A"
    assert score.waste_ratio == 0.0
    assert score.recoverable_dollars == 0.0


def test_waste_ratio_uses_only_quality_safe_findings_by_default() -> None:
    findings = [
        _finding(5.0, QualityRisk.none),
        _finding(3.0, QualityRisk.low),
        _finding(2.0, QualityRisk.review),  # excluded: quality not measured
    ]
    score = compute_score(findings=findings, total_dollars=10.0)

    assert score.waste_ratio == pytest.approx(0.8)  # (5+3)/10, review-risk excluded
    assert score.efficiency == 20
    assert score.recoverable_dollars == pytest.approx(10.0)  # headline includes everything


def test_review_risk_counts_once_quality_is_measured() -> None:
    findings = [_finding(5.0, QualityRisk.review)]
    score = compute_score(
        findings=findings, total_dollars=10.0, quality_factor=1.0, quality_measured=True
    )
    assert score.waste_ratio == pytest.approx(0.5)


def test_quality_factor_scales_efficiency_down() -> None:
    score = compute_score(findings=[], total_dollars=10.0, quality_factor=0.8)
    assert score.efficiency == 80  # 100 * 1.0 * 0.8


def test_efficiency_never_goes_below_zero_or_above_hundred() -> None:
    huge_waste = compute_score(findings=[_finding(100.0)], total_dollars=10.0)
    assert huge_waste.efficiency == 0

    zero_cost = compute_score(findings=[], total_dollars=0.0)
    assert zero_cost.efficiency == 100


def test_quality_factor_placeholder_is_honest_about_being_unmeasured() -> None:
    assert compute_quality_factor(None) == (1.0, False)
    assert compute_quality_factor({"tasks": {}}) == (1.0, False)
