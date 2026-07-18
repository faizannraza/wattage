"""This is Phase 2's actual exit-criterion assertion, automated: wattage's
convergence classifier must beat the SHA-256 baseline's F1 on the labeled
adversarial set, with at least one stalled-loop example the baseline misses
and wattage catches.
"""

from benchmarks.adversarial_fixtures import FIXTURES
from benchmarks.harness import run_benchmark
from wattage.convergence.classify import LoopClass


def test_wattage_beats_the_sha256_baseline_on_f1() -> None:
    result = run_benchmark(FIXTURES)
    assert result.wattage_scores.f1 > result.baseline_scores.f1


def test_wattage_achieves_perfect_recall_on_the_labeled_set() -> None:
    """Every non-convergent fixture here was hand-verified (test_adversarial_
    fixtures.py); wattage should recognize all of them as non-productive."""
    result = run_benchmark(FIXTURES)
    assert result.wattage_scores.recall == 1.0


def test_baseline_misses_a_concrete_stalled_case_wattage_catches() -> None:
    result = run_benchmark(FIXTURES)
    found = False
    for fixture, wattage_pred, baseline_flagged in zip(
        FIXTURES, result.wattage_predictions, result.baseline_predictions, strict=True
    ):
        is_stalled = fixture.label == "stalled" and wattage_pred == LoopClass.stalled
        if is_stalled and not baseline_flagged:
            found = True
            break
    assert found, "expected at least one stalled fixture the baseline misses"


def test_baseline_still_catches_the_easy_byte_identical_control_case() -> None:
    """Confirms the comparison isn't rigged — the baseline should succeed on
    at least the trivial case where args are byte-identical every time."""
    result = run_benchmark(FIXTURES)
    control = next(f for f in FIXTURES if f.name == "identical_repeat_control")
    index = FIXTURES.index(control)
    assert result.baseline_predictions[index] is True
