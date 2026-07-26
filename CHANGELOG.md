# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.1] — unreleased

### Fixed

- **The HTML flame graph ("burn map") was vulnerable to stored XSS via trace
  content.** Flame-graph node names (tool names, model strings, retrieval
  queries) come straight from an OTLP trace — untrusted input, since
  `wattage report --html` will render whatever file it's given — and were
  embedded into `const DATA = ...` via a bare `json.dumps()`. That escapes
  for JSON string syntax but not for HTML: a literal `</script>` inside a
  string value (e.g. a tool name of `</script><script>...` closed the
  legitimate `<script>` tag early and let the rest execute as a new,
  attacker-controlled script — in this self-contained report that's
  routinely opened directly in a browser and shared/screenshotted. Verified
  in a real browser: a crafted tool name previously fired an injected
  script; confirmed inert after the fix (data still round-trips correctly
  to the exact original string). Fixed with a `_json_for_script()` helper
  that escapes `<`, `>`, `&`, and the U+2028/U+2029 line separators as
  `\uXXXX` sequences before embedding (the same approach Django's
  `json_script` filter uses) — a no-op for `JSON.parse`, but the sequence
  can no longer terminate the tag.
- **JUnit XML output could be invalid XML.** Finding `evidence`/`fix` text
  (derived from trace content — untrusted input on the `wattage ci` path)
  and `--fail-on` failure reasons were escaped with `xml.sax.saxutils.escape()`
  before being written into `render_junit`'s `name="..."`/`message="..."`
  attributes, but that function only escapes `&`/`<`/`>` — not a literal
  `"`. A single quote character in a finding's evidence or fix text (e.g.
  quoted tool-call arguments) terminated the attribute early and produced
  malformed XML that a JUnit-consuming CI system (GitLab, CircleCI,
  Jenkins) couldn't parse. Fixed: attribute values now go through
  `xml.sax.saxutils.quoteattr()`, which escapes and quotes correctly for
  any input.
- **A malformed trace could break `wattage ci`'s exit-code contract.** A
  span missing its required `spanId` field (or any other structurally
  malformed span — a non-object entry, a trace whose top-level JSON wasn't
  even an object) raised a bare `KeyError`/`TypeError`/`AttributeError`
  straight out of the OTLP adapter, which `run_ci` didn't catch. That
  surfaced as an uncaught-exception traceback and Python's default exit
  code 1 — indistinguishable, at the CI-gate boundary, from exit code 1's
  actual documented meaning ("a fail-on threshold breached," i.e. a real
  cost regression). A bad trace could look exactly like a passing build
  failing its cost gate. Fixed: the adapter now raises a dedicated
  `AdapterError` for any malformed span or trace shape, and `run_ci` maps
  it to the already-documented exit code 3 ("ingestion error"), alongside
  the existing missing-file/invalid-JSON/empty-trace cases.
- **`wattage.yaml` didn't actually exist as a load path.** `config.py`'s own
  docstring called itself "wattage.yaml config schema" and CONTRIBUTING.md
  told detector authors a user could turn a detector off "in wattage.yaml,"
  but no code path anywhere ever read such a file — every command
  constructed a bare `WattageConfig()` with defaults, unconditionally, no
  matter what was on disk. Fixed: a new `load_config()` auto-discovers
  `./wattage.yaml` in the current working directory (matching the existing
  `.wattage/baseline.json` convention), or loads an explicit path via the
  new `--config` flag on all four commands (`report`, `score`, `badge`,
  `ci`); a bad explicit path (missing file, invalid YAML, schema violation)
  is a clear exit code 2, matching the project's existing config-error
  convention. While documenting this fix, found and closed the same bug
  class twice more inside `CIConfig` itself: `badge_out`/`sarif_out` were
  schema fields that were never actually consulted as fallbacks for
  `--badge-out`/`--sarif-out`, and `pr_comment: bool` was fully vestigial
  (zero real consumers — the Action's actual PR-comment toggle is its own
  independent `INPUT_PR_COMMENT` env var). Removed the dead `pr_comment`
  field and wired `badge_out`, `sarif_out`, and a new `pr_comment_out` field
  as real fallbacks in `wattage ci`, exactly like the pre-existing, working
  `baseline_path`/`fail_on` pattern.
- **An unknown/unpriced model (e.g. a real model not yet in the vendored
  pricing registry, which covers only 9 models today) silently rendered
  as `A (100) · $0.0000 · this trace looks efficient`** in `report`,
  `score`, and `badge` — with only a buried Python `UserWarning` on
  stderr as any signal something was wrong. `Report.unpriced_calls`
  existed and was correctly populated but was only ever checked by
  `wattage ci`; the three most commonly used commands never looked at
  it. Fixed: all three now name the specific unpriced model(s)
  (`Report.unpriced_models`, a new field) and mark the grade/cost as
  incomplete rather than showing a plausible-looking number — the
  terminal report leads with a prominent warning, the badge shows a
  neutral grey "unpriced" pill instead of a letter grade (this is the
  surface most likely to sit unattended on a public README), and
  `wattage score` replaces the headline entirely rather than pair a fake
  grade with a caveat. `wattage ci`'s exit-4 reason now also names the
  model, not just a bare count.
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

- **`numpy` and `pydantic-settings` dropped as runtime dependencies.**
  Found by an independent adversarial review: both were declared in
  `pyproject.toml`'s core `dependencies` but never imported anywhere in
  `src/` (confirmed by grep across the whole tree) — dead weight on every
  install, and `pydantic-settings` pulled in `python-dotenv` transitively
  along with it. `config.py` (the module the removed
  `WATTAGE_BUILD_DOC.md`'s build plan expected to use
  `pydantic-settings`) actually just uses plain `pydantic.BaseModel` +
  `yaml.safe_load` — a real, already-shipped, already-tested
  implementation, so this is a documentation-catching-up-to-code removal,
  not a functional change. The unused `numpy.*` mypy override is gone too.
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
