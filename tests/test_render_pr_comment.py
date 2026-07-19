from wattage.baseline import Baseline, record_run
from wattage.models import Finding, QualityRisk, Report, Score, Severity
from wattage.render.pr_comment import render_pr_comment


def _report(
    efficiency: int,
    grade: str,
    findings: list[Finding],
    recoverable: float,
    quality_measured: bool = False,
) -> Report:
    return Report(
        trace_source="t.json",
        total_dollars=1.0,
        token_breakdown={},
        findings=findings,
        score=Score(
            efficiency=efficiency,
            grade=grade,
            waste_ratio=0.1,
            quality_factor=1.0,
            quality_measured=quality_measured,
            recoverable_dollars=recoverable,
        ),
        pricing_version="2026-07-18-verified",
        generated_at="2026-01-01T00:00:00Z",
    )


def _finding(
    detector_id: str, tokens: int, dollars: float, risk: QualityRisk = QualityRisk.none
) -> Finding:
    return Finding(
        id=detector_id,
        severity=Severity.high,
        wasted_tokens=tokens,
        wasted_dollars=dollars,
        quality_risk=risk,
        evidence="e",
        fix="enable caching",
    )


def test_no_baseline_yet_is_noted_honestly() -> None:
    report = _report(50, "F", [_finding("prefix_churn", 658, 0.0001)], 0.0001)
    comment = render_pr_comment(report, Baseline())
    assert "no baseline yet" in comment
    assert "prefix_churn" in comment
    assert "▲ new" in comment


def test_score_delta_shown_against_baseline() -> None:
    baseline = record_run(Baseline(), _report(90, "A", [], 0.0), passed=True)
    current = _report(70, "C", [_finding("verbosity", 500, 0.02)], 0.02)
    comment = render_pr_comment(current, baseline)
    assert "▼ 20 vs baseline" in comment


def test_table_has_exactly_one_row_per_detector_with_nonzero_waste() -> None:
    baseline = record_run(
        Baseline(), _report(90, "A", [_finding("prefix_churn", 100, 0.01)], 0.01), passed=True
    )
    current = _report(90, "A", [_finding("prefix_churn", 100, 0.01)], 0.01)
    comment = render_pr_comment(current, baseline)

    table_lines = [
        line
        for line in comment.splitlines()
        if line.startswith("|") and "Detector" not in line and "---" not in line
    ]
    assert len(table_lines) == 1
    assert "prefix_churn" in table_lines[0]


def test_percent_change_is_computed_correctly() -> None:
    baseline = record_run(
        Baseline(), _report(90, "A", [_finding("prefix_churn", 100, 0.05)], 0.05), passed=True
    )
    current = _report(50, "F", [_finding("prefix_churn", 300, 0.4)], 0.4)
    comment = render_pr_comment(current, baseline)
    assert "+700%" in comment


def test_top_fix_is_the_highest_dollar_finding() -> None:
    report = _report(
        60,
        "D",
        [
            _finding("verbosity", 100, 0.001),
            _finding("prefix_churn", 5000, 0.5),
        ],
        0.501,
    )
    comment = render_pr_comment(report, Baseline())
    assert "**Top fix:** enable caching" in comment


def test_quality_neutral_note_only_for_none_risk_findings() -> None:
    report = _report(60, "D", [_finding("model_mismatch", 100, 0.01, QualityRisk.review)], 0.01)
    comment = render_pr_comment(report, Baseline())
    assert "quality-neutral" not in comment


def test_footer_reflects_quality_measured_state() -> None:
    unmeasured = render_pr_comment(_report(90, "A", [], 0.0, quality_measured=False), Baseline())
    assert "quality: unmeasured" in unmeasured

    measured = render_pr_comment(_report(90, "A", [], 0.0, quality_measured=True), Baseline())
    assert "quality: measured" in measured
    assert "unmeasured" not in measured
