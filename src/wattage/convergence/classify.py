"""Progress score combination + loop classification (doc §5.3).

Classification only looks at the *trailing* run of sub-threshold iterations
(ending at the loop's last iteration), not any bad stretch anywhere in the
history — a loop that dipped and recovered is productive; what matters for
"is this loop non-convergent" and for wasted-token attribution (§5.4) is
whether it's *currently* stuck. Within a long-enough trailing bad streak,
oscillation (a detected cycle) is checked first since it's the most specific
signature, then the stalled signature (evidence and state both flat while
context keeps growing — the shallow-guard blind spot doc §5.1 calls out),
and general thrashing is the catch-all.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from wattage.convergence.signals import IterationSignals


class LoopClass(str, Enum):
    productive = "productive"
    thrashing = "thrashing"
    oscillating = "oscillating"
    stalled = "stalled"


@dataclass(frozen=True)
class ConvergenceWeights:
    """Field names match the doc's §5.3 notation (E/S/P/O/G) exactly, on purpose."""

    E: float = 0.40
    S: float = 0.20
    P: float = 0.20
    O: float = 0.15  # noqa: E741 (ambiguous-with-zero; matches doc notation deliberately)
    G: float = 0.05


@dataclass(frozen=True)
class ClassificationThresholds:
    theta_prog: float = 0.25
    consecutive_k: int = 3
    oscillation_threshold: float = 0.6
    stall_evidence_threshold: float = 0.15
    stall_state_threshold: float = 0.15
    stall_growth_threshold: float = 0.5


def combine_progress(signals: IterationSignals, weights: ConvergenceWeights) -> float:
    score = (
        weights.E * signals.evidence_gain
        + weights.S * signals.state_delta
        + weights.P * signals.goal_proximity
        - weights.O * signals.oscillation
        - weights.G * signals.growth_penalty
    )
    return max(0.0, min(1.0, score))


def last_productive_index(progress_scores: list[float], theta_prog: float) -> int | None:
    productive_indices = [i for i, p in enumerate(progress_scores) if p >= theta_prog]
    return productive_indices[-1] if productive_indices else None


def classify_loop(
    iteration_signals: list[IterationSignals],
    progress_scores: list[float],
    thresholds: ClassificationThresholds,
) -> LoopClass:
    n = len(progress_scores)
    last_prod = last_productive_index(progress_scores, thresholds.theta_prog)
    streak = n if last_prod is None else n - 1 - last_prod

    if streak < thresholds.consecutive_k:
        return LoopClass.productive

    trailing = iteration_signals[-streak:]

    trailing_oscillation = max((s.oscillation for s in trailing), default=0.0)
    if trailing_oscillation >= thresholds.oscillation_threshold:
        return LoopClass.oscillating

    stalled_iters = sum(
        1
        for s in trailing
        if s.evidence_gain <= thresholds.stall_evidence_threshold
        and s.state_delta <= thresholds.stall_state_threshold
        and s.growth_penalty >= thresholds.stall_growth_threshold
    )
    if stalled_iters >= thresholds.consecutive_k:
        return LoopClass.stalled

    return LoopClass.thrashing
