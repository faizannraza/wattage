# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.1] — unreleased

### Fixed

- **`report`/`score`/`badge` dumped raw Python tracebacks for ordinary
  input errors.** Unlike `wattage ci`, these three commands caught nothing
  around ingestion — a missing or malformed `--source` trace, a malformed
  `--pricing` override (invalid YAML), or a malformed `--quality` map
  (invalid JSON) all produced a full Rich-rendered traceback instead of a
  clean message. Reproduced all four cases. Fixed: a shared
  `_input_errors_or_exit()` helper catches `OSError`/
  `json.JSONDecodeError`/`yaml.YAMLError`/`AdapterError` around
  `build_report`/`build_trace_and_report` in all three commands, printing
  a one-line `error: ...` message to stderr and exiting 1 — matching the
  polish `ci` already had for the same underlying errors.
- **The HTML flame graph could corrupt itself via a template-placeholder
  collision in trace content.** `render_html` substituted its template
  tokens (`__TREE_JSON__`, `__FINDINGS_HTML__`, etc.) with sequential
  `str.replace()` calls on one growing string — and `__FINDINGS_HTML__`
  (which embeds trace-derived, HTML-escaped finding evidence/fix text) was
  substituted *before* `__TREE_JSON__`. Reproduced: a tool literally named
  `__TREE_JSON__` in trace content produced a finding whose evidence text
  contains that literal string; once inserted into the page, the later
  `__TREE_JSON__` replacement re-matched it and substituted the *entire*
  serialized flame-graph tree JSON into the findings sidebar. Not
  executable (the earlier XSS fix's escaping held), but genuine
  untrusted-input-driven page corruption. Fixed: a single regex pass over
  the static template with a dict-lookup callback, which by construction
  never rescans already-substituted content — verified with the same
  reproduction (now shows the literal tool name) and visually confirmed in
  a real browser.
- **A corrupt `.wattage/baseline.json` broke `wattage ci`'s exit-code
  contract.** `run_ci`'s `try/except` around ingestion never extended to
  `load_baseline`/`record_run`/`save_baseline` — found by an independent
  adversarial review, then reproduced four ways: merge-conflict markers
  left in the file (the realistic trigger — two branches both updating a
  committed baseline), invalid JSON, a schema violation, and a corrupt
  timestamp in a history entry all raised uncaught
  (`pydantic.ValidationError` / `ValueError` / `OSError`) straight through
  `run_ci`, landing on Python's default exit code 1 — indistinguishable
  from exit 1's real documented meaning, "a fail-on threshold breached."
  A corrupt baseline file could red out a build as a phantom cost
  regression instead of reporting the real problem. Fixed: the whole
  baseline load/evaluate/record/save block now maps any such failure to
  the already-documented exit code 2 ("config/usage error").
- **SARIF's `driver.version` was hardcoded to `"0.1.0"` while the package
  was already `0.1.1`.** `render_sarif()`'s default parameter never tracked
  `wattage.__version__`, and the CLI never overrode it — every SARIF
  upload to GitHub's Security tab misidentified the exact engine version
  that produced the results, and would drift further at every future
  release with zero test coverage catching it. Fixed: the default now
  resolves to `__version__` directly, and the CLI passes it explicitly.
- **Pinning the GitHub Action didn't actually pin the analysis engine.**
  `action.yml` ran `uv tool install wattage --quiet` — unpinned, so it
  always installed whatever was newest on PyPI regardless of which tag a
  workflow pinned (`uses: faizannraza/wattage/action@v0.1.0`). A workflow
  that had deliberately pinned to an old, known-good tag (docs/ci.md's own
  stated reason: "a future Wattage release can't silently change what your
  existing workflows run") could still get a newer engine version's
  scoring/detector changes without warning. Fixed: installs from
  `$(dirname github.action_path)` instead — `github.action_path` is this
  action's own checkout at the exact ref the workflow pinned, one
  directory up from `action.yml` is the package root — so the installed
  version is tied to the pinned ref by construction, not by a
  manually-maintained version string that could drift out of sync at the
  next release.
- **`prefix_churn` could recommend a fix that wouldn't work.**
  `min_cacheable_prefix_tokens` was parsed from the pricing registry into
  every `ModelPrice` (1024 tokens for most vendored models, 4096 for
  Claude Haiku) but never consulted anywhere — so a resent prefix smaller
  than a model's own minimum cacheable size still got flagged with "enable
  prompt caching" as the fix, even though the provider won't create a
  cache entry that small at all; the recommended fix genuinely would not
  help. `find_resent_segments` (shared by this detector and
  `benchmarks/frontier.py`'s before/after simulation, so both changed
  together and stay consistent) now takes the pricing registry and
  excludes any resend below the resending call's own model's
  `min_cacheable_prefix_tokens`. An unknown model's threshold can't be
  checked, so those segments are left in rather than guessed away.
- **`prefix_churn`'s reported dollar figure overstated the achievable
  savings by ~10%.** `Finding.wasted_dollars` credited the *full* resent
  cost (`resent_tokens * price.input`) as recoverable, as if enabling
  caching made a re-sent prefix entirely free. It doesn't: every vendored
  model's `cache_read_mult` is 0.10, meaning a cache hit still bills at
  10% of the input rate. `benchmarks/frontier.py`'s real-data before/after
  simulation already accounted for this correctly (`resent_dollars -
  cached_dollars`) — so the same fix's savings were reported two different
  ways depending which part of the codebase you asked, and the one users
  actually see (the report/badge/PR-comment "$X recoverable" headline) was
  the inflated one. Fixed: `wasted_dollars` is now `resent_tokens *
  price.input * (1 - price.cache_read_mult)`, matching frontier.py exactly
  (verified: they now agree on the same real trace to within floating-point
  rounding). Severity is unaffected — it's still keyed on the gross resent
  cost's share of task spend (doc §4.1), which describes the size of the
  problem independent of how much of it is ultimately recoverable.
- **`docs/detectors/prefix_churn.md` cited an uncited statistic.** "independent
  audits have found re-sent context accounts for roughly 60% of a typical
  agent's spend" had no source anywhere in the repo — an unverifiable claim
  attributed to unnamed "independent audits," exactly the kind of
  plausible-looking-but-unfounded number this project exists to avoid in
  its own reports, let alone its own docs. Checked whether this project's
  own committed benchmark scenarios could stand in for it instead: the real
  measured prefix_churn share of total cost across them ranges from 0% to
  84%, too wide and too dependent on each fixture's specific design to
  responsibly compress into one "roughly 60%"-style headline number. Fixed
  by dropping the fabricated statistic and stating the real, verifiable
  reason this detector is high-leverage: an agent loop resends its entire
  system prompt, tool schemas, and growing history on every turn absent
  caching, so the miss compounds with every additional call.
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
