"""Benchmark harness (doc plan 2.9): runs wattage's convergence classifier
and the SHA-256 exact-match baseline against the labeled adversarial set,
computes precision/recall/F1, and surfaces a concrete example the baseline
misses and wattage catches.

Run: `python -m benchmarks.harness`
"""

from __future__ import annotations

from dataclasses import dataclass

from benchmarks.adversarial_fixtures import FIXTURES, LabeledLoop
from benchmarks.baseline_sha256 import baseline_flags_loop
from wattage.convergence.classify import (
    ClassificationThresholds,
    ConvergenceWeights,
    LoopClass,
    classify_loop,
    combine_progress,
)
from wattage.convergence.embed import build_embedder
from wattage.convergence.signals import compute_iteration_signals


@dataclass(frozen=True)
class PRF1:
    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int
    tn: int


def compute_prf1(predictions: list[bool], truths: list[bool]) -> PRF1:
    pairs = list(zip(predictions, truths, strict=True))
    tp = sum(1 for p, t in pairs if p and t)
    fp = sum(1 for p, t in pairs if p and not t)
    fn = sum(1 for p, t in pairs if not p and t)
    tn = sum(1 for p, t in pairs if not p and not t)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return PRF1(precision=precision, recall=recall, f1=f1, tp=tp, fp=fp, fn=fn, tn=tn)


def classify_with_wattage(fixtures: list[LabeledLoop]) -> list[LoopClass]:
    embedder = build_embedder("local")
    weights = ConvergenceWeights()
    thresholds = ClassificationThresholds()
    predictions = []
    for fixture in fixtures:
        signals = compute_iteration_signals(fixture.loop.iterations, embedder)
        progress = [combine_progress(s, weights) for s in signals]
        predictions.append(classify_loop(signals, progress, thresholds))
    return predictions


def classify_with_baseline(fixtures: list[LabeledLoop], window: int = 5) -> list[bool]:
    return [baseline_flags_loop(f.loop, window=window) for f in fixtures]


@dataclass(frozen=True)
class BenchmarkResult:
    wattage_scores: PRF1
    baseline_scores: PRF1
    wattage_predictions: list[LoopClass]
    baseline_predictions: list[bool]


def run_benchmark(fixtures: list[LabeledLoop] = FIXTURES) -> BenchmarkResult:
    truths_binary = [f.label != "productive" for f in fixtures]

    wattage_predictions = classify_with_wattage(fixtures)
    wattage_binary = [p != LoopClass.productive for p in wattage_predictions]
    baseline_predictions = classify_with_baseline(fixtures)

    return BenchmarkResult(
        wattage_scores=compute_prf1(wattage_binary, truths_binary),
        baseline_scores=compute_prf1(baseline_predictions, truths_binary),
        wattage_predictions=wattage_predictions,
        baseline_predictions=baseline_predictions,
    )


def print_report(fixtures: list[LabeledLoop], result: BenchmarkResult) -> None:
    print("=== Binary classification: non-convergent vs productive ===")
    print(f"{'Classifier':<12}{'Precision':>12}{'Recall':>10}{'F1':>10}")
    w, b = result.wattage_scores, result.baseline_scores
    print(f"{'Wattage':<12}{w.precision:>12.2f}{w.recall:>10.2f}{w.f1:>10.2f}")
    print(f"{'SHA-256':<12}{b.precision:>12.2f}{b.recall:>10.2f}{b.f1:>10.2f}")
    print()

    print("=== Per-fixture detail ===")
    print(f"{'Fixture':<30}{'Truth':<13}{'Wattage':<13}{'Baseline'}")
    for f, wp, bp in zip(
        fixtures, result.wattage_predictions, result.baseline_predictions, strict=True
    ):
        baseline_label = "flagged" if bp else "not flagged"
        print(f"{f.name:<30}{f.label:<13}{wp.value:<13}{baseline_label}")
    print()

    print("=== Baseline blind-spot example ===")
    for f, wp, bp in zip(
        fixtures, result.wattage_predictions, result.baseline_predictions, strict=True
    ):
        if f.label == "stalled" and wp.value == "stalled" and not bp:
            print(f"'{f.name}': wattage correctly classifies STALLED; baseline says NOT FLAGGED.")
            print(f"  {f.note}")
            break
    else:
        print("(no stalled-and-baseline-missed example found)")


if __name__ == "__main__":
    result = run_benchmark()
    print_report(FIXTURES, result)
