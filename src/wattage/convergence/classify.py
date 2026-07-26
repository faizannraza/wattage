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

"Recovered" must be earned by genuine, observable content, not merely by
ending the loop: an iteration with no captured action/result text (a
chat-only final answer — the normal shape, since message content isn't
captured by the real adapter) falls back to a neutral signal value that
happens to clear theta_prog on its own. last_productive_index excludes
such iterations from counting as "the loop got back on track" — a loop
that thrashed throughout and simply gave up with an uninformative final
answer must still be flagged, the same as if it had never answered at
all. This replaced an earlier, coarser gate (Loop.reached_success) that
exempted a loop's entire classification whenever it ended without a
pending tool call, regardless of whether the final answer actually
represented progress — real-world testing showed that gate silently
disabled the detector on most real, complete traces, since agents
virtually always produce *some* final response, good or bad.
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


def last_productive_index(
    progress_scores: list[float], has_content: list[bool], theta_prog: float
) -> int | None:
    """An iteration only counts as evidence the loop got back on track if it
    had genuine, observable content to judge in the first place. A
    chat-only final answer with no captured message text (has_content=
    False -- the normal case, since LLMCall.messages is never populated by
    the real adapter) falls back to the embedder's neutral "no signal"
    score for E and S, which happens to clear theta_prog on its own -- that
    must never be mistaken for evidence the loop actually recovered, or a
    loop that thrashed throughout and then simply gave up with an
    uninformative final answer would be wrongly exempted from every check
    below."""
    productive_indices = [
        i
        for i, (p, content) in enumerate(zip(progress_scores, has_content, strict=True))
        if p >= theta_prog and content
    ]
    return productive_indices[-1] if productive_indices else None


def classify_loop(
    iteration_signals: list[IterationSignals],
    progress_scores: list[float],
    thresholds: ClassificationThresholds,
) -> LoopClass:
    has_content = [s.has_observable_content for s in iteration_signals]
    n = len(progress_scores)
    last_prod = last_productive_index(progress_scores, has_content, thresholds.theta_prog)
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
