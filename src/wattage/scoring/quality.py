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


class QualityMapError(Exception):
    """A --quality map has an unexpected shape (present but malformed, not
    simply missing an optional field). Maps to exit code 2 (config/usage
    error) -- this is supplementary input, not trace content."""


def compute_quality_factor(
    quality_map: dict[str, Any] | None, target: float = 0.90
) -> tuple[float, bool]:
    if not quality_map:
        return 1.0, False

    tasks = quality_map.get("tasks", {})
    if not isinstance(tasks, dict):
        raise QualityMapError(
            f"quality map's 'tasks' must be an object, got {type(tasks).__name__}"
        )

    scores = []
    for task_id, t in tasks.items():
        if not isinstance(t, dict) or "eval_score" not in t:
            continue  # a task with no eval_score is legitimate -- not every step is scored
        eval_score = t["eval_score"]
        if isinstance(eval_score, bool) or not isinstance(eval_score, int | float):
            raise QualityMapError(
                f"quality map task {task_id!r}'s eval_score must be a number, got {eval_score!r}"
            )
        scores.append(eval_score)
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
