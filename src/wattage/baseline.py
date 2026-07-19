""".wattage/baseline.json (doc §7.8/§11.1): the committed baseline + rolling
window that lets CI tell a noise-floor flake from a real regression.

The noise-floor protection is structural, not statistical: `last_passing`
only ever updates on a run that actually passed the gate, so one flaky bad
run can never corrupt the reference point a future run is compared against.
The rolling window is a plain historical log (useful for trend reporting)
rather than an adaptive variance model — the doc's own config
(`cost_delta_pct_above: 5`) is a flat percentage threshold, so that's what
this computes against, honestly, rather than inventing a statistical model
the config doesn't ask for.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from wattage.models import Report


class DetectorSnapshot(BaseModel):
    wasted_tokens: int = 0
    wasted_dollars: float = 0.0


class RunSnapshot(BaseModel):
    recorded_at: str
    efficiency: int
    grade: str
    total_dollars: float
    per_detector: dict[str, DetectorSnapshot] = Field(default_factory=dict)


class Baseline(BaseModel):
    last_passing: RunSnapshot | None = None
    history: list[RunSnapshot] = Field(default_factory=list)


class DetectorDelta(BaseModel):
    detector_id: str
    current_tokens: int
    baseline_tokens: int
    current_dollars: float
    baseline_dollars: float

    @property
    def is_new(self) -> bool:
        return self.baseline_tokens == 0 and self.baseline_dollars == 0.0

    @property
    def pct_change(self) -> float | None:
        if self.baseline_dollars <= 0:
            return None  # no baseline to compute a percentage against
        return (self.current_dollars - self.baseline_dollars) / self.baseline_dollars * 100


def snapshot_from_report(report: Report) -> RunSnapshot:
    per_detector: dict[str, DetectorSnapshot] = {}
    for finding in report.findings:
        snap = per_detector.setdefault(finding.id, DetectorSnapshot())
        snap.wasted_tokens += finding.wasted_tokens
        snap.wasted_dollars += finding.wasted_dollars
    return RunSnapshot(
        recorded_at=report.generated_at,
        efficiency=report.score.efficiency,
        grade=report.score.grade,
        total_dollars=report.total_dollars,
        per_detector=per_detector,
    )


def load_baseline(path: str | Path) -> Baseline:
    p = Path(path)
    if not p.exists():
        return Baseline()
    return Baseline.model_validate_json(p.read_text(encoding="utf-8"))


def save_baseline(path: str | Path, baseline: Baseline) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(baseline.model_dump_json(indent=2), encoding="utf-8")


def record_run(baseline: Baseline, report: Report, passed: bool, window_days: int = 7) -> Baseline:
    snapshot = snapshot_from_report(report)
    history = [*baseline.history, snapshot]
    cutoff = datetime.fromisoformat(snapshot.recorded_at) - timedelta(days=window_days)
    history = [s for s in history if datetime.fromisoformat(s.recorded_at) >= cutoff]
    last_passing = snapshot if passed else baseline.last_passing
    return Baseline(last_passing=last_passing, history=history)


def diff_against_baseline(report: Report, baseline: Baseline) -> list[DetectorDelta]:
    current = snapshot_from_report(report)
    baseline_detectors = baseline.last_passing.per_detector if baseline.last_passing else {}
    detector_ids = sorted(set(current.per_detector) | set(baseline_detectors))

    deltas = []
    for detector_id in detector_ids:
        cur = current.per_detector.get(detector_id, DetectorSnapshot())
        base = baseline_detectors.get(detector_id, DetectorSnapshot())
        deltas.append(
            DetectorDelta(
                detector_id=detector_id,
                current_tokens=cur.wasted_tokens,
                baseline_tokens=base.wasted_tokens,
                current_dollars=cur.wasted_dollars,
                baseline_dollars=base.wasted_dollars,
            )
        )
    return deltas


def cost_delta_pct(report: Report, baseline: Baseline) -> float | None:
    if baseline.last_passing is None or baseline.last_passing.total_dollars <= 0:
        return None
    reference = baseline.last_passing.total_dollars
    return (report.total_dollars - reference) / reference * 100
