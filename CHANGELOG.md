# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.1] — unreleased

### Fixed

- **The convergence engine barely fired on real, complete agent traces.**
  Found by an independent adversarial review, then confirmed with two
  separate empirical reproductions: `nonconvergence` exempted a loop's
  entire classification whenever its last iteration was a plain chat
  response with no pending tool call (`Loop.reached_success`) — which is
  structurally indistinguishable from an agent that thrashed the whole
  time and then simply gave up with an uninformative final answer (real
  message content isn't captured by the adapter). Worse, the underlying
  signal computation itself treated an empty-content final iteration as
  "productive" via the embedder's neutral no-signal fallback, independent
  of that gate. Since real agents almost always end with *some* final
  text, this meant the detector only reliably fired on traces cut off
  mid-tool-call — not the far more common "burned money thrashing, then
  gave up" shape. Fixed at the signal level: an iteration with no genuine
  observable content can no longer be credited as evidence a loop
  recovered, and the `reached_success` short-circuit was removed
  entirely. Validated against the flagship F1 1.00 vs. 0.25 benchmark
  (unchanged), all 10 hand-verified fixtures (unchanged), and all three
  of this release's real-world test scenarios (byte-identical results) —
  zero regression, only the previously-invisible case now fires.
- **`recoverable_dollars` could exceed a trace's own total cost.** Detectors
  that legitimately flag the same underlying calls from different angles
  (e.g. `prefix_churn` and `nonconvergence` on a stalled loop) were summed
  with no de-duplication, so the headline "$X recoverable" figure (`wattage
  score`, the badge) could claim more money was recoverable than the trace
  cost in total. Now capped at `total_dollars` — an honest conservative
  ceiling rather than a fabricated-looking number.
- **`RetrievalCall.chunks` was never populated** by the OTLP adapter, so any
  agent using genuine OTel `embeddings`-kind spans for retrieval (rather
  than modeling retrieval as a plain tool call) got zero signal from
  `retrieval_thrash` and the convergence engine's evidence-gain — silently,
  with no warning. `normalize_retrieval_call` now reads a `retrieval.chunks`
  attribute (JSON-encoded or an already-decoded OTLP array), and
  `retrieval_thrash`'s own waste tally now accounts for chunk content
  alongside tool-call results.
- **Sub-cent findings displayed as literal `$0.0000`** in the terminal
  report, the HTML flame graph, and PR comments — a genuinely nonzero,
  honestly-computed finding reading as "zero waste." A shared
  `format_dollars()` helper now expands precision for amounts that would
  otherwise round away to nothing.
- **The terminal report's box width depended on the live terminal**,
  so the exact same report rendered differently across environments,
  undermining "share a screenshot, docs show exactly this." Pinned to a
  fixed width by default.
- Fixed a missing `uv run` prefix in `docs/convergence.md`'s benchmark
  command (raised `ModuleNotFoundError` as literally written).

### Documented

- Clarified that `cache_gap` intentionally stays silent for providers with
  no cache-write premium (`cache_write_mult == 1.0` — OpenAI today) even
  with a fully-unredeemed cache write; this is by design, not a miss.

### Added

- `docs/getting-started.md` — a "Getting your first trace" guide covering
  both "I already have OTel traces" and a real, runnable, verified
  zero-instrumentation path (`examples/instrument_minimal.py`).
- `.github/workflows/ci.yml` (repo's own CI: pytest/ruff/mypy on a
  3.10/3.13 matrix, plus a `mkdocs build --strict` job) and
  `.github/workflows/test-action.yml` (runs the real composite Action
  against a real trace on every push touching `action/**`).
- Issue templates, PR template, `CODE_OF_CONDUCT.md`, `SECURITY.md`.
- `examples/quality.json` — a real, verified example of the `--quality`
  flag's schema.
- A README hero GIF (real terminal recording via VHS, not a mockup).

### Removed

- `WATTAGE_BUILD_DOC.md` dropped from git tracking (kept locally) — an
  internal planning document, not part of the public-facing repo.

Most of the above were found and verified via a rigorous testing pass
against 3 large, realistic multi-agent scenarios (customer-support
orchestration, a 22-iteration autonomous coding-agent loop, and a
3-level-deep nested RAG research system) run end-to-end through the real
pipeline — not synthetic unit fixtures alone. These traces, their
generator scripts, and the ground-truth spec they were checked against are
committed in `benchmarks/scenarios/` — reproducible, not an unfalsifiable
claim. The convergence engine fix came from a follow-up independent
adversarial review (deliberately run on a different model with zero prior
context) and two further empirical reproductions before any code changed.

## [0.1.0] — first public release

Core detectors (`prefix_churn`, `cache_gap`, `verbosity`,
`redundant_tool_calls`, `nonconvergence`, `retrieval_thrash`,
`model_mismatch`, `reasoning_overspend`), the convergence engine (F1 1.00
vs. a SHA-256 exact-match baseline's 0.25), the CI cost-regression gate,
the GitHub Action, and the mkdocs documentation site. Published on PyPI
(`wattage`) and npm (`wattage-cli`).
