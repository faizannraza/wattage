# Wattage

**A Kill-A-Watt meter for your AI agents.** Point it at a trace and it tells
you exactly where your tokens are being burned and wasted, prices each waste
pattern in real dollars, prescribes a fix, and can fail your CI when a change
makes your agent measurably more expensive.

<!--
TODO(maintainer): record a ~10s terminal GIF of the one-liner below producing
the report, and one of `wattage report --html` opened in a browser, then
replace this comment with:
![wattage report demo](docs/assets/demo.gif)
-->

## Install and run

```bash
uvx wattage report trace.json
```

No config file, no API key, fully offline — point it at an [OTLP JSON](https://opentelemetry.io/docs/specs/otlp/)
trace export and it prices every call and runs every detector. Try it right
now against the fixture shipped in this repo:

```bash
git clone https://github.com/muhammadfaizanraza/wattage
cd wattage && uv sync
uv run wattage report examples/sample_trace.json
```

```
╭──── ⚡ wattage — examples/sample_trace.json ────╮
│ Token Efficiency: A (100)   Total cost: $0.0602 │
│ quality: unmeasured                             │
╰─────────────────────────────────────────────────╯
      Token breakdown
┏━━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ Category       ┃ Tokens ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ input          │  18450 │
│ output         │    320 │
│ cache_read     │      0 │
│ cache_creation │      0 │
│ reasoning      │      0 │
└────────────────┴────────┘
No findings — this trace looks efficient.
pricing: 2026-07-18-verified
```

Or get a self-contained, shareable HTML flame graph instead of the terminal
view:

```bash
uv run wattage report examples/sample_trace.json --html report.html
```

## The evidence, not a marketing claim

Wattage's standout feature is the **convergence engine** — the
`nonconvergence` detector, which catches an agent thrashing through a loop
without making real progress, including patterns a naive exact-match
duplicate detector structurally cannot see (a retry with a fresh timestamp
each time, an oscillation between two strategies, a "productive-looking"
stall where every call is technically unique but nothing is actually
learned).

Rather than assert that, we built a hand-reviewed set of 10 labeled
synthetic loops and benchmarked Wattage's classifier against a real
SHA-256 exact-match baseline implementation:

| Classifier | Precision | Recall | F1 |
|---|---|---|---|
| **Wattage** | 1.00 | 1.00 | **1.00** |
| SHA-256 exact-match | 1.00 | 0.14 | 0.25 |

Reproduce it yourself — no cherry-picking, no hidden setup:

```bash
uv run python -m benchmarks.harness
```

And on a genuine captured agent trace (not synthetic — see
[`benchmarks/traces/README.md`](benchmarks/traces/README.md) for provenance),
Wattage's `prefix_churn` fix simulation shows a **44.7% cost reduction**
(`$0.000199 → $0.000110`) from enabling prompt caching on the stable prefix —
small dollar figures because it's a 3-turn demo trace, but the mechanism is
identical at production scale. Run it against your own traces for numbers
that matter:

```bash
uv run python -c "from benchmarks.frontier import build_frontier; print(build_frontier())"
```

Full methodology: [The Convergence Engine](docs/convergence.md).

## The badge

```bash
uv run wattage badge trace.json --out wattage-badge.svg
```

```markdown
![Wattage](wattage-badge.svg)
```

Wire `--badge-out` into your CI job (see below) so it regenerates on every
merge to your default branch, and the badge in your README stays live.

## How it works

Three surfaces, one normalized data model underneath
(`sessions → tasks → loops → iterations → calls`), built from
[OpenTelemetry GenAI semantic-convention](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
traces:

- **`wattage report`** — ingests a trace, prices every call against a
  vendored, dated pricing snapshot, and runs eight detectors:

  | Detector | Catches |
  |---|---|
  | `prefix_churn` | Stable context re-sent instead of cached |
  | `cache_gap` | Caching attempted but under-redeemed by later reads |
  | `verbosity` | Output far beyond what the step needed |
  | `redundant_tool_calls` | The same tool call repeated (exact or fuzzy) |
  | `nonconvergence` | Loops that thrash, oscillate, or stall without progress |
  | `retrieval_thrash` | Repeated retrieval that never yields relevant results |
  | `model_mismatch` | A pricier model doing work a cheaper one could handle |
  | `reasoning_overspend` | Heavy reasoning-token spend on a simple step |

  Every finding is priced in real dollars, includes a concrete fix, and is
  tagged with a `quality_risk` tier (`none` / `low` / `review`) — a fix that
  could plausibly change output quality (a model downgrade, less reasoning)
  only counts toward your score once a `--quality` map backs it with real
  evidence. Full detail: [Detectors](docs/detectors/index.md).

- **`wattage score` / `wattage badge`** — a single 0–100 Token Efficiency
  grade for a README badge or a CI gate.

- **`wattage ci`** — the cost-regression gate (below).

Wattage never fabricates a number: an unpriced model leaves that call's cost
at zero (and fails `wattage ci` loudly, exit code 4) rather than guessing;
an unmeasured quality signal is reported as `unmeasured`, not assumed fine.

## CI integration

```yaml
# .github/workflows/wattage.yml
name: Wattage
on:
  pull_request:
    paths: ["agents/**", "prompts/**", "src/**"]
concurrency:
  group: wattage-${{ github.ref }}
  cancel-in-progress: true
jobs:
  token-efficiency:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Generate trace fixture
        run: python scripts/run_agent_fixture.py > trace.json
      - name: Wattage cost-regression gate
        uses: muhammadfaizanraza/wattage/action@v1
        with:
          source: trace.json
          baseline: .wattage/baseline.json
          fail-on: "score_below:80,cost_delta_pct_above:5,any_critical:true"
          pr-comment: "true"
```

Fails the build (exit code 1) when your agent regresses past the threshold
you set, posts a per-detector delta table as a PR comment, and emits SARIF
(shows up in GitHub's Security tab) and JUnit XML for any other CI system.
The baseline is a small committed JSON file — noise-floor protection is
structural, not statistical: it only ever updates on a run that actually
passed the gate. Full reference: [CI Integration](docs/ci.md).

## Contributing

Detectors are discovered through a Python entry-point group, so adding one
doesn't require touching this repo's core pipeline — see
[CONTRIBUTING.md](CONTRIBUTING.md) for the full "write a detector" walkthrough,
using [`cache_gap`](src/wattage/detectors/cache_gap.py) as the reference
example.

## License

[Apache-2.0](LICENSE)
