from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from wattage.baseline import (
    Baseline,
    cost_delta_pct,
    diff_against_baseline,
    load_baseline,
    record_run,
    save_baseline,
)
from wattage.models import Finding, QualityRisk, Report, Score, Severity


def _report(total_dollars: float, findings: list[Finding], when: datetime) -> Report:
    return Report(
        trace_source="t",
        total_dollars=total_dollars,
        token_breakdown={},
        findings=findings,
        score=Score(
            efficiency=80,
            grade="B",
            waste_ratio=0.1,
            quality_factor=1.0,
            quality_measured=False,
            recoverable_dollars=sum(f.wasted_dollars for f in findings),
        ),
        pricing_version="v",
        generated_at=when.isoformat(),
    )


def _finding(
    detector_id: str, tokens: int, dollars: float, severity: Severity = Severity.medium
) -> Finding:
    return Finding(
        id=detector_id,
        severity=severity,
        wasted_tokens=tokens,
        wasted_dollars=dollars,
        quality_risk=QualityRisk.none,
        evidence="e",
        fix="f",
    )


def test_load_missing_baseline_is_empty(tmp_path: Path) -> None:
    baseline = load_baseline(tmp_path / "does-not-exist.json")
    assert baseline.last_passing is None
    assert baseline.history == []


def test_cost_delta_is_none_without_a_baseline() -> None:
    baseline = Baseline()
    report = _report(1.0, [], datetime.now(timezone.utc))
    assert cost_delta_pct(report, baseline) is None


def test_record_run_sets_last_passing_and_appends_history() -> None:
    baseline = Baseline()
    now = datetime.now(timezone.utc)
    report = _report(1.0, [_finding("prefix_churn", 100, 0.05)], now)

    baseline = record_run(baseline, report, passed=True)

    assert baseline.last_passing is not None
    assert baseline.last_passing.total_dollars == 1.0
    assert len(baseline.history) == 1


def test_failing_run_does_not_update_last_passing() -> None:
    now = datetime.now(timezone.utc)
    baseline = record_run(Baseline(), _report(1.0, [], now), passed=True)

    later = now + timedelta(hours=1)
    baseline = record_run(baseline, _report(5.0, [], later), passed=False)

    assert baseline.last_passing is not None
    assert baseline.last_passing.total_dollars == 1.0  # unchanged
    assert len(baseline.history) == 2  # still recorded for the log


def test_cost_delta_pct_matches_hand_computed_percentage() -> None:
    now = datetime.now(timezone.utc)
    baseline = record_run(Baseline(), _report(1.0, [], now), passed=True)
    regression = _report(1.5, [], now + timedelta(hours=1))
    assert cost_delta_pct(regression, baseline) == pytest.approx(50.0)


def test_diff_flags_a_new_detector_not_seen_in_baseline() -> None:
    now = datetime.now(timezone.utc)
    baseline = record_run(Baseline(), _report(1.0, [], now), passed=True)
    current = _report(1.2, [_finding("verbosity", 50, 0.1)], now + timedelta(hours=1))

    deltas = diff_against_baseline(current, baseline)
    verbosity_delta = next(d for d in deltas if d.detector_id == "verbosity")
    assert verbosity_delta.is_new is True
    assert verbosity_delta.pct_change is None  # can't compute a % from zero baseline


def test_diff_computes_exact_percent_change_for_an_existing_detector() -> None:
    now = datetime.now(timezone.utc)
    baseline = record_run(
        Baseline(), _report(1.0, [_finding("prefix_churn", 100, 0.05)], now), passed=True
    )
    current = _report(1.5, [_finding("prefix_churn", 300, 0.4)], now + timedelta(hours=1))

    deltas = diff_against_baseline(current, baseline)
    delta = next(d for d in deltas if d.detector_id == "prefix_churn")
    assert delta.pct_change == pytest.approx(700.0)
    assert delta.is_new is False


def test_rolling_window_prunes_entries_older_than_the_window() -> None:
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=10)

    baseline = record_run(Baseline(), _report(0.5, [], old), passed=True)
    baseline = record_run(baseline, _report(0.6, [], now), passed=True, window_days=7)

    assert len(baseline.history) == 1
    assert baseline.history[0].total_dollars == 0.6


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    baseline = record_run(
        Baseline(), _report(1.0, [_finding("prefix_churn", 100, 0.05)], now), passed=True
    )
    path = tmp_path / "baseline.json"
    save_baseline(path, baseline)

    reloaded = load_baseline(path)
    assert reloaded.last_passing is not None
    assert reloaded.last_passing.total_dollars == 1.0
    assert reloaded.last_passing.per_detector["prefix_churn"].wasted_dollars == 0.05
