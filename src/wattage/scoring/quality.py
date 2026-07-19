"""Quality gating (doc §6.3).

quality_factor down-weights the Token Efficiency score when a supplied
--quality quality.json shows the run's actual task eval scores falling
below a target — so a cheap-but-wrong agent can't score well.
quality_measured is only True when real eval scores were actually found in
the supplied map; a missing or empty map honestly reports "unmeasured"
rather than a fabricated confident 1.0.
"""

from __future__ import annotations

from typing import Any


def compute_quality_factor(
    quality_map: dict[str, Any] | None, target: float = 0.90
) -> tuple[float, bool]:
    if not quality_map:
        return 1.0, False

    tasks = quality_map.get("tasks", {})
    scores = [t["eval_score"] for t in tasks.values() if isinstance(t, dict) and "eval_score" in t]
    if not scores:
        return 1.0, False

    average_quality = sum(scores) / len(scores)
    factor = min(1.0, average_quality / target) if target > 0 else 1.0
    return max(0.0, factor), True


def downgrade_pass_rate(
    quality_map: dict[str, Any] | None, step_role: str, candidate_model: str
) -> float | None:
    """quality_map["downgrade_evals"]["{step_role}@{candidate_model}"]["pass_rate"]
    (doc Appendix C shape). None if absent — callers must not guess a rate."""
    if not quality_map:
        return None
    downgrade_evals = quality_map.get("downgrade_evals", {})
    entry = downgrade_evals.get(f"{step_role}@{candidate_model}")
    if not isinstance(entry, dict):
        return None
    pass_rate = entry.get("pass_rate")
    return float(pass_rate) if isinstance(pass_rate, int | float) else None
