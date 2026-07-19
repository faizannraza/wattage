# The Convergence Engine

This is Wattage's technical moat: the `nonconvergence` detector catches agents that are stuck in a loop, spinning through iterations without actually making progress toward their goal — and it catches patterns that the "shallow loop guards" already built into several agent frameworks structurally cannot see.

## Why shallow loop guards aren't enough

The most common defense against runaway agent loops today is exact-match duplicate detection: hash each tool call's name and arguments, keep a sliding window of recent hashes, and flag it if you see the same hash twice. This is cheap and it catches the most obvious case — but it has three specific blind spots:

- **Fuzzy loops.** An agent retrying the same failing action with a slightly different argument each time (an incrementing attempt counter, a fresh timestamp) never hashes equal to its own prior attempt, even though it's the same unproductive retry in every way that matters.
- **Semantic oscillation.** An agent alternating between two strategies — `check_status` → `retry_action` → `check_status` → `retry_action` — with each individual call looking "new" relative to the *immediately* preceding one.
- **Productive-looking stalls.** An agent whose every tool call is technically unique (different tool, different arguments, every single time) but whose actual results are boilerplate and whose context keeps growing regardless. An exact-match detector sees zero duplicates and concludes everything is fine.

## What Wattage measures instead

Rather than asking "have I seen this exact call before," Wattage measures **progress** directly, per iteration, using five signals:

- **Evidence gain (E)** — how novel this iteration's tool/retrieval results are against everything seen so far in the loop (cosine novelty over a lightweight embedding).
- **State delta (S)** — how much the agent's chosen action actually changed from just the *immediately prior* iteration (a local, not cumulative, comparison — the thing that keeps this a distinct signal from E).
- **Oscillation (O)** — periodic repetition in the sequence of actions taken (period 2 or more only; a single repeated action is `thrashing`'s signature, not oscillation's), robust to argument noise because it keys on tool names, not exact arguments.
- **Growth-vs-information (G)** — how many new context tokens this iteration cost relative to how much genuinely new evidence arrived, independent of E, so a loop can have low evidence gain yet still be assessed on whether that repetition was *cheap* or *expensive*.
- **Goal proximity (P)** — only meaningful when an explicit goal signal is supplied; defaults to a neutral value otherwise, never a guess.

These combine into a per-iteration progress score, and a loop is classified as **productive**, **thrashing** (the same unproductive action repeated), **oscillating** (a detected cycle), or **stalled** (context keeps growing, evidence and state both stay flat — the exact-match blind spot). A loop that reached success is never flagged, on the philosophy that a loop which got there in the end shouldn't be second-guessed for how it got there.

## The evidence

Rather than assert this works, the project built a hand-reviewed, empirically-verified set of 10 labeled synthetic loops (`benchmarks/adversarial_fixtures.py`) — three productive, three thrashing, two oscillating, two stalled, each one specifically constructed and hand-checked so its label is defensible on inspection, not just whatever the code happened to output — and ran both Wattage's classifier and a real reference implementation of the SHA-256 exact-match baseline against it (`benchmarks/harness.py`).

**Wattage: F1 1.00. The SHA-256 baseline: F1 0.25** (recall 0.14 — it catches exactly one of the seven genuinely non-convergent cases: the one where the arguments happened to be byte-identical every time). The concrete example the baseline misses entirely: a loop where every single tool call is technically unique, yet Wattage correctly identifies it as stalled because the context kept growing while the results stayed boilerplate.

Run it yourself:

```bash
python -m benchmarks.harness
```

## Embeddings: local by default, no API key required

The novelty computation needs *some* notion of text similarity. Rather than requiring a heavy ML dependency just to get a useful default, Wattage ships a dependency-free character n-gram hashing embedder that works out of the box, and upgrades automatically to `sentence-transformers` (materially better novelty detection) if you `pip install wattage[embeddings]` — the convergence engine works either way; only the quality of the "which loops are borderline" judgment changes.

## What's next

An optional sampled LLM judge (off by default) can resolve genuinely ambiguous cases where the structural signals disagree — it's built and tested, but never invoked automatically, so the core engine never depends on a live API key. Runtime enforcement — the same signals running live to warn, then nudge, then hard-stop a thrashing agent in-flight — is the natural next step once this diagnostic layer has proven itself on real traces, which is exactly the sequencing this project followed.
