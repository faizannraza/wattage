"""Confirms every labeled adversarial fixture (benchmarks/adversarial_fixtures.py)
still classifies as its hand-verified ground-truth label. A failure here
means classify.py/signals.py's behavior changed in a way that invalidates a
previously-verified label — re-run benchmarks/verify_fixtures.py to see the
underlying signals before deciding whether the fixture or the code is wrong.
"""

import pytest

from benchmarks.adversarial_fixtures import FIXTURES, LabeledLoop
from wattage.convergence.classify import (
    ClassificationThresholds,
    ConvergenceWeights,
    classify_loop,
    combine_progress,
)
from wattage.convergence.embed import build_embedder
from wattage.convergence.signals import compute_iteration_signals


@pytest.mark.parametrize("fixture", FIXTURES, ids=[f.name for f in FIXTURES])
def test_fixture_matches_its_ground_truth_label(fixture: LabeledLoop) -> None:
    embedder = build_embedder("local")
    weights = ConvergenceWeights()
    thresholds = ClassificationThresholds()

    signals = compute_iteration_signals(fixture.loop.iterations, embedder)
    progress = [combine_progress(s, weights) for s in signals]
    predicted = classify_loop(signals, progress, thresholds)

    assert predicted.value == fixture.label, (
        f"{fixture.name}: expected {fixture.label!r}, classifier said {predicted.value!r}. "
        f"({fixture.note})"
    )


def test_fixture_set_covers_all_four_classes() -> None:
    labels = {f.label for f in FIXTURES}
    assert labels == {"productive", "thrashing", "oscillating", "stalled"}


def test_fixture_names_are_unique() -> None:
    names = [f.name for f in FIXTURES]
    assert len(names) == len(set(names))
