# Detectors

Each detector is an independent, individually toggleable plugin that reads a normalized session and emits zero or more findings — a named waste pattern with severity, wasted tokens, wasted dollars, an evidence trail, and a prescribed fix. Third-party detectors register the same way the built-in ones do, via a `wattage.detectors` entry point (see `CONTRIBUTING.md` for how to write one).

| Detector | Detects | Quality risk |
|---|---|---|
| [`prefix_churn`](prefix_churn.md) | Re-sent context not being cached | None |
| [`cache_gap`](cache_gap.md) | Caching attempted but under-redeemed by reads | None |
| [`verbosity`](verbosity.md) | Output over-generation with no cap | Low |
| [`redundant_tool_calls`](redundant_tool_calls.md) | The same tool call repeated pointlessly | None |
| [`nonconvergence`](../convergence.md) | Agent loops thrashing/oscillating/stalling without progress | None |
| [`retrieval_thrash`](retrieval_thrash.md) | Repeated retrieval yielding no new evidence | Review |
| [`model_mismatch`](model_mismatch.md) | A premium model used for a step a cheaper one would handle | Review |
| [`reasoning_overspend`](reasoning_overspend.md) | Excess reasoning tokens on a simple step | Review |

## Quality risk, explained

Every finding is tagged with a **quality risk** tier:

- **None** — the fix is purely a billing/caching change; it can't affect what the model actually sees or produces.
- **Low** — the fix nudges output format/length; a small, usually-safe behavior change.
- **Review** — the fix could plausibly change output quality (a cheaper model, less reasoning, less retrieval). These findings always show up in the report so you know about them, but they **never count toward the Token Efficiency score** unless you supply a `--quality quality.json` map showing the fix is actually safe. That's a hard rule, not a default that can drift: a cheap-but-wrong agent can't score well just because nothing was measured.

## A shared limitation, stated once

Several detectors approximate signals that would be exact if message content were captured (prompt diffing, precise per-call token attribution) — most production traces don't capture full message content for privacy/size reasons, so Wattage falls back to token-count-based heuristics with explicit guards against the most obvious false positives. Each detector's page names its specific approximation and the guard that keeps it honest, rather than glossing over it.
