# Wattage

**A Kill‑A‑Watt meter for your AI agents.**

Wattage reads [OpenTelemetry GenAI semantic-convention](https://opentelemetry.io/docs/specs/semconv/gen-ai/) traces — the standard most agent frameworks and observability tools already emit — and tells you exactly where your tokens are being burned and wasted. It quantifies the dollar cost of each waste pattern, prescribes a fix, computes a quality-aware Token Efficiency score, and can fail your CI when a change makes your agents more expensive.

## What it is (and isn't)

Wattage is a **diagnosis + prescription + gate**, not another dashboard:

- It **consumes** the traces your existing observability tool (Langfuse, Helicone, an OTel Collector, whatever) already produces — it doesn't replace them.
- It **names specific waste patterns** with dollar figures and a fix, rather than just showing you a bill.
- It **never enforces anything automatically** — findings are recommendations you apply, not prompts it silently rewrites. Runtime enforcement (killing waste in-flight) is a deliberately separate, later, opt-in capability.

## The three surfaces

1. **`wattage report`** — a priced, findings-quantified report for one trace: terminal, JSON, or a self-contained HTML flame graph.
2. **`wattage score` / `wattage badge`** — a single 0–100 Token Efficiency grade you can drop into a README.
3. **`wattage ci`** — a cost-regression gate: fails a PR when a change makes your agent measurably more expensive, with exact, documented exit codes.

## Quick start

```bash
uvx wattage report trace.json
```

That's it — no config file, no API key, fully offline. Point it at an [OTLP JSON](adapters.md) export of your agent's trace and it prices every call, runs every detector, and prints a report.

## Where to go next

- **[Adapters](adapters.md)** — what trace formats Wattage reads, and how it tolerates the real-world naming differences between frameworks.
- **[Detectors](detectors/index.md)** — the eight waste patterns Wattage looks for, one page each.
- **[The Convergence Engine](convergence.md)** — the standout: how Wattage catches agents thrashing in unproductive loops, and why exact-match duplicate detection can't.
- **[CI Integration](ci.md)** — wiring `wattage ci` into a GitHub Action so cost regressions fail the build.

## A note on honesty

Every dollar figure, every score, and every "typical savings" claim Wattage produces comes from an actual computation against your real trace and the current vendored pricing data — never a guess dressed up as a number. When Wattage doesn't have enough information to say something confidently (an unpriced model, an unmeasured quality signal, a genuinely ambiguous loop), it says so explicitly instead of filling the gap with a plausible-looking number. That's a design principle, not an afterthought — see the individual detector pages for exactly which limitations each one is honest about.
