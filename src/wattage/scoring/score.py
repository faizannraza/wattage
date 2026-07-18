"""Token Efficiency score (doc §6.2/6.3).

`waste_ratio` (and therefore the grade) only counts a finding's dollars once
they're quality-safe: `none`/`low` risk findings always count; `review`-risk
findings (model downgrades, reasoning cuts — none of Phase 1's detectors
emit these yet) only count once quality has actually been measured. This is
what stops a cheap-but-wrong agent from scoring well.

`recoverable_dollars` is the unfiltered headline instead — the doc's own
framing is that dollars move executives, so it reports every identified
saving opportunity regardless of quality-risk tier, while the grade stays
conservative.
"""

from __future__ import annotations

from wattage.models import Finding, QualityRisk, Score

_GRADE_BANDS = ((90, "A"), (80, "B"), (70, "C"), (60, "D"))


def grade_for(efficiency: int) -> str:
    for threshold, grade in _GRADE_BANDS:
        if efficiency >= threshold:
            return grade
    return "F"


def compute_score(
    findings: list[Finding],
    total_dollars: float,
    quality_factor: float = 1.0,
    quality_measured: bool = False,
    monthly_projection: float | None = None,
) -> Score:
    quality_safe_dollars = sum(
        f.wasted_dollars for f in findings if f.quality_risk in (QualityRisk.none, QualityRisk.low)
    )
    if quality_measured:
        quality_safe_dollars += sum(
            f.wasted_dollars for f in findings if f.quality_risk == QualityRisk.review
        )

    waste_ratio = quality_safe_dollars / total_dollars if total_dollars > 0 else 0.0
    waste_ratio = min(max(waste_ratio, 0.0), 1.0)

    efficiency = round(100 * (1 - waste_ratio) * quality_factor)
    efficiency = min(max(efficiency, 0), 100)

    recoverable_dollars = sum(f.wasted_dollars for f in findings)

    return Score(
        efficiency=efficiency,
        grade=grade_for(efficiency),
        waste_ratio=waste_ratio,
        quality_factor=quality_factor,
        quality_measured=quality_measured,
        recoverable_dollars=recoverable_dollars,
        monthly_projection=monthly_projection,
    )
