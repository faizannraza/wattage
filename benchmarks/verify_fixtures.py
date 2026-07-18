"""Run once, by hand, whenever benchmarks/adversarial_fixtures.py changes:
confirms every fixture's assigned label matches wattage's actual
classification output, and prints the underlying signals so a human can
sanity-check *why*. This is not a pass/fail gate (a mismatch here means the
fixture or the label needs fixing, not that the code is broken) — it's the
tool used to build confidence in the labels before trusting them anywhere.
"""

from __future__ import annotations

from benchmarks.adversarial_fixtures import FIXTURES
from wattage.convergence.classify import (
    ClassificationThresholds,
    ConvergenceWeights,
    classify_loop,
    combine_progress,
)
from wattage.convergence.embed import build_embedder
from wattage.convergence.signals import compute_iteration_signals

if __name__ == "__main__":
    embedder = build_embedder("local")
    weights = ConvergenceWeights()
    thresholds = ClassificationThresholds()

    mismatches = []
    for fixture in FIXTURES:
        signals = compute_iteration_signals(fixture.loop.iterations, embedder)
        progress = [combine_progress(s, weights) for s in signals]
        predicted = classify_loop(signals, progress, thresholds)

        status = "OK" if predicted.value == fixture.label else "MISMATCH"
        if status == "MISMATCH":
            mismatches.append(fixture.name)

        print(f"[{status}] {fixture.name}: expected={fixture.label} predicted={predicted.value}")
        for i, (s, p) in enumerate(zip(signals, progress, strict=True)):
            print(
                f"    iter{i}: E={s.evidence_gain:.2f} S={s.state_delta:.2f} "
                f"O={s.oscillation:.2f} G={s.growth_penalty:.2f} progress={p:.2f}"
            )

    print()
    if mismatches:
        print(f"{len(mismatches)} mismatch(es): {mismatches}")
    else:
        print(f"All {len(FIXTURES)} fixtures verified correctly.")
