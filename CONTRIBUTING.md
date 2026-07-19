# Contributing to Wattage

Thanks for considering it. This document covers the dev loop and, in
detail, how to add a new detector — the most common contribution.

## Dev setup

```bash
git clone https://github.com/faizannraza/wattage
cd wattage
uv sync --extra dev --extra docs
```

Run the checks the project holds itself to before every commit:

```bash
uv run pytest              # tests (unit, golden, hypothesis property tests)
uv run ruff check .         # lint
uv run ruff format --check . # formatting
uv run mypy                 # strict type checking (src/wattage, not tests)
```

All four must be clean. `mypy` runs in `strict = true` mode (see
`pyproject.toml`); every function needs full type annotations.

## Ground rules

- **No fabricated numbers.** Every dollar figure, F1 score, or benchmark
  claim in this codebase — in code comments, docs, or commit messages —
  must come from an actual run against real or clearly-labeled-synthetic
  data. If you don't have a real number, say the thing is unmeasured
  rather than inventing a plausible one. See `docs/convergence.md` for
  what this looks like in practice (the SHA-256 baseline comparison is a
  real, reproducible benchmark, not an assertion).
- **Detectors never guess a price.** If a call's model has no pricing
  registry entry, the cost engine leaves it at zero and marks it
  `unpriced` (`Cost.unpriced`, `Report.unpriced_calls`) — it does not
  estimate. `wattage ci` treats this as a hard error (exit code 4).
- **Quality-risk honesty.** If a detector's fix could plausibly change
  output quality (a model downgrade, less reasoning effort, shorter
  output), tag it `QualityRisk.review` or `QualityRisk.low`, not `none`.
  `review`-tier findings never count toward the Token Efficiency score
  unless a `--quality` map backs them with real pass-rate evidence
  (`ModelMismatchConfig.require_quality_map` is the reference example).

## Writing a new detector

Detectors are discovered through a Python entry-point group
(`wattage.detectors`), not a hardcoded list — this is what lets an
external package add a detector to Wattage without touching this repo.

### 1. The interface

A detector is anything satisfying `wattage.detectors.base.Detector`:

```python
class Detector(ABC):
    id: str
    default_enabled: bool = True

    @abstractmethod
    def analyze(self, session: Session, ctx: AnalysisContext) -> list[Finding]:
        """Pure function of a session (+ ctx). Deterministic, side-effect free."""
```

`analyze` must be a pure function — no I/O, no randomness, no mutation of
`session`. This is what makes detectors independently unit-testable and
safe to run in any order. `AnalysisContext` (`src/wattage/detectors/base.py`)
gives you the pricing engine, resolved config, and optionally an embedder,
judge, and quality map — use only what you need.

Two helpers on the same module save you re-deriving call ordering:

- `ordered_llm_calls(task)` — every `LLMCall` in a task (direct + all loop
  iterations), sorted by `start_ns`.
- `ordered_tool_calls(task)` — the `ToolCall` equivalent.

### 2. A minimal real example

`src/wattage/detectors/cache_gap.py` is a good template — short, single
responsibility, and its docstring is honest about what it can't detect:

```python
class CacheGapDetector:
    id = "cache_gap"
    default_enabled = True

    def analyze(self, session: Session, ctx: AnalysisContext) -> list[Finding]:
        findings: list[Finding] = []
        for task in session.tasks:
            ...
            findings.append(
                Finding(
                    id=self.id,
                    severity=severity,
                    wasted_tokens=wasted_tokens,
                    wasted_dollars=wasted_dollars,
                    quality_risk=QualityRisk.none,
                    evidence="...",  # specific numbers, not a vague description
                    fix="...",       # one concrete, actionable change
                    span_ids=span_ids,
                )
            )
        return findings
```

`Finding.evidence` should cite the actual numbers that triggered it (see
`cache_gap.py`'s `f"{total_creation} cache-write tokens vs {total_read}
cache-read tokens..."`), not a generic description of the pattern — the
person reading the report should be able to verify the finding themselves
from the evidence string alone.

### 3. Register the entry point

Add one line to `pyproject.toml`:

```toml
[project.entry-points."wattage.detectors"]
your_detector = "wattage.detectors.your_module:YourDetectorClass"
```

Then `uv sync` to pick it up. `load_detectors()`
(`src/wattage/detectors/base.py`) discovers it automatically from there —
nothing else in the pipeline needs to know it exists.

### 4. Add a config model

Even a detector with no tunable behavior needs an `enabled: bool = True`
config model, so users can turn it off in `wattage.yaml`:

```python
# src/wattage/config.py
class YourDetectorConfig(BaseModel):
    enabled: bool = True
    # any thresholds your detector needs, with a sensible, documented default
```

Add it to `DetectorsConfig` under the same key as your entry-point name —
`load_detectors()` looks up `config.detectors.<id>` by attribute name, so
the key must match `id` exactly.

### 5. Write tests

At minimum, mirror `tests/test_detector_cache_gap.py`'s shape:

- One golden test per distinct behavior (fires under condition X, doesn't
  fire under condition Y, severity escalates past threshold Z).
- At least one Hypothesis property test asserting an invariant that should
  hold across the whole input space, not just your hand-picked examples —
  e.g. "if reads always meet or exceed writes, this never fires."

Run just your new tests while iterating:

```bash
uv run pytest tests/test_detector_your_module.py -v
```

### 6. Document it

Add `docs/detectors/your_detector.md` (see any existing page for the
shape: what it detects, how it works, the fix, and — importantly — its
`quality_risk` tier and known limitations, stated plainly). Link it from
`docs/detectors/index.md` and from `mkdocs.yml`'s nav. Build the docs
locally before submitting:

```bash
uv run mkdocs build --strict
```

## Real-trace validation

If your change touches ingestion (`src/wattage/adapters/`,
`src/wattage/normalize.py`), don't validate against synthetic fixtures
alone — `benchmarks/traces/` has a genuine captured agent trace
(see `benchmarks/traces/README.md` for provenance) specifically because
synthetic fixtures encode your own assumptions about what a trace looks
like, and real traces are where those assumptions break. Prefer fixing a
gap in the adapter/normalizer over adapting the trace to fit.

## Pull requests

Keep PRs scoped to one detector, one bug, or one surface at a time. Include:

- What the change does and, for a new detector, the real waste pattern it
  targets.
- Test output showing the new tests pass and nothing else broke
  (`uv run pytest`).
- For anything touching pricing or benchmarks: where the numbers came
  from, if not already obvious from the code.
