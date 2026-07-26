import pytest

from wattage.convergence.classify import (
    ClassificationThresholds,
    ConvergenceWeights,
    LoopClass,
    classify_loop,
    combine_progress,
    last_productive_index,
)
from wattage.convergence.signals import IterationSignals

WEIGHTS = ConvergenceWeights()
THRESHOLDS = ClassificationThresholds()


def _sig(
    e: float, s: float, o: float, g: float, p: float = 0.5, has_content: bool = True
) -> IterationSignals:
    return IterationSignals(
        evidence_gain=e,
        state_delta=s,
        oscillation=o,
        growth_penalty=g,
        goal_proximity=p,
        has_observable_content=has_content,
    )


def test_combine_progress_matches_formula() -> None:
    signals = _sig(e=0.8, s=0.8, o=0.1, g=0.2, p=0.5)
    expected = (
        WEIGHTS.E * 0.8 + WEIGHTS.S * 0.8 + WEIGHTS.P * 0.5 - WEIGHTS.O * 0.1 - WEIGHTS.G * 0.2
    )
    assert combine_progress(signals, WEIGHTS) == pytest.approx(expected)


def test_combine_progress_clamped_to_zero_and_one() -> None:
    assert combine_progress(_sig(0, 0, 1, 1, 0), WEIGHTS) == 0.0
    assert combine_progress(_sig(1, 1, 0, 0, 1), WEIGHTS) == pytest.approx(
        min(1.0, WEIGHTS.E + WEIGHTS.S + WEIGHTS.P)
    )


def test_last_productive_index_finds_the_last_iteration_at_or_above_theta() -> None:
    scores = [0.5, 0.1, 0.6, 0.2]
    assert last_productive_index(scores, [True] * 4, theta_prog=0.25) == 2


def test_last_productive_index_none_when_never_productive() -> None:
    scores = [0.1, 0.1, 0.1]
    assert last_productive_index(scores, [True] * 3, theta_prog=0.25) is None


def test_last_productive_index_skips_an_otherwise_qualifying_iteration_with_no_content() -> None:
    """The core fix for the reached_success bug: an iteration that clears
    theta_prog only because it had nothing observable to judge (a
    chat-only final answer with no captured message text -- the neutral
    "no signal" embedder fallback) must not be credited as evidence the
    loop recovered."""
    scores = [0.1, 0.1, 0.35]
    has_content = [True, True, False]  # index 2 clears theta_prog, but has no real content
    assert last_productive_index(scores, has_content, theta_prog=0.25) is None

    # The same scores, but the last iteration's content IS genuine -- it
    # should count.
    assert last_productive_index(scores, [True, True, True], theta_prog=0.25) == 2


def test_productive_loop_stays_above_theta_throughout() -> None:
    signals = [_sig(0.8, 0.8, 0, 0.1) for _ in range(5)]
    scores = [combine_progress(s, WEIGHTS) for s in signals]
    assert classify_loop(signals, scores, THRESHOLDS) == LoopClass.productive


def test_brief_dip_below_k_iterations_is_still_productive() -> None:
    signals = [_sig(0.8, 0.8, 0, 0.1), _sig(0.05, 0.05, 0, 0.3), _sig(0.8, 0.8, 0, 0.1)]
    scores = [combine_progress(s, WEIGHTS) for s in signals]
    assert classify_loop(signals, scores, THRESHOLDS) == LoopClass.productive


def test_sustained_low_progress_without_oscillation_or_stall_signature_is_thrashing() -> None:
    signals = [_sig(0.05, 0.05, 0, 0.3) for _ in range(5)]
    scores = [combine_progress(s, WEIGHTS) for s in signals]
    assert classify_loop(signals, scores, THRESHOLDS) == LoopClass.thrashing


def test_high_oscillation_in_the_trailing_streak_is_oscillating() -> None:
    signals = [_sig(0.1, 0.1, 0.9, 0.2) for _ in range(5)]
    scores = [combine_progress(s, WEIGHTS) for s in signals]
    assert classify_loop(signals, scores, THRESHOLDS) == LoopClass.oscillating


def test_flat_evidence_and_state_with_high_growth_is_stalled() -> None:
    signals = [_sig(0.02, 0.02, 0, 0.8) for _ in range(5)]
    scores = [combine_progress(s, WEIGHTS) for s in signals]
    assert classify_loop(signals, scores, THRESHOLDS) == LoopClass.stalled


def test_oscillation_takes_priority_over_stall_signature() -> None:
    """A trailing streak that satisfies both the oscillation and stall
    thresholds is reported as oscillating — the more specific signature."""
    signals = [_sig(0.02, 0.02, 0.9, 0.8) for _ in range(5)]
    scores = [combine_progress(s, WEIGHTS) for s in signals]
    assert classify_loop(signals, scores, THRESHOLDS) == LoopClass.oscillating


def test_thrashing_streak_ending_in_an_empty_content_answer_is_still_thrashing() -> None:
    """Regression test for the reached_success bug: a loop that thrashes
    throughout and then simply gives up with an uninformative final answer
    (no captured content) must still be flagged -- that final iteration's
    neutral, content-free score must not read as a genuine recovery."""
    thrashing = [_sig(0.05, 0.05, 0, 0.3) for _ in range(5)]
    empty_final_answer = _sig(0.4, 0.4, 0, 0.0, has_content=False)
    signals = [*thrashing, empty_final_answer]
    scores = [combine_progress(s, WEIGHTS) for s in signals]

    assert classify_loop(signals, scores, THRESHOLDS) == LoopClass.thrashing


@pytest.mark.parametrize("k", [1, 2, 3, 5])
def test_consecutive_k_is_respected(k: int) -> None:
    thresholds = ClassificationThresholds(consecutive_k=k)
    signals = [_sig(0.05, 0.05, 0, 0.3) for _ in range(k)]
    scores = [combine_progress(s, WEIGHTS) for s in signals]
    assert classify_loop(signals, scores, thresholds) == LoopClass.thrashing

    # One iteration short of k should still read as productive.
    if k > 1:
        short_signals = signals[:-1]
        short_scores = scores[:-1]
        assert classify_loop(short_signals, short_scores, thresholds) == LoopClass.productive
