# Large real-world scenario traces

Three large, synthetic-but-realistic OTLP JSON traces, built to stress-test
the full pipeline (ingestion → sessionization → all 8 detectors → pricing →
scoring) at a scale and complexity `benchmarks/adversarial_fixtures.py`'s
small hand-labeled fixtures don't reach: multi-agent nesting, mixed
providers, and several detectors firing simultaneously in one trace.

`GROUND_TRUTH.md` is the spec — written before any trace was built, stating
exactly what each detector should (and should not) find, so results are
checked against a pre-committed expectation rather than rationalized after
the fact.

- **`scenario1_customer_support.py`** → `scenario1.json` — an e-commerce
  support system: one orchestrator with 3 nested specialist sub-agents
  (2-level nesting, 3 siblings). Exercises `prefix_churn`,
  `reasoning_overspend`, `redundant_tool_calls`, `nonconvergence`
  (thrashing), `retrieval_thrash`, `verbosity`, and mixed
  anthropic/openai pricing in one session.
- **`scenario2_coding_agent.py`** → `scenario2.json` — a single 22-iteration
  autonomous coding-agent loop (no agent nesting — the catch-all-task
  path). The main stress test of the convergence engine at real scale: a
  genuine `stalled` classification over a much longer trajectory than the
  synthetic fixtures use.
- **`scenario3_research_agent.py`** → `scenario3.json` — a RAG research
  system with 3 levels of nesting and 3 siblings under a non-root parent,
  plus orphan pre-processing calls outside any agent span. The deepest
  sessionization stress test.

Regenerate any of them (byte-for-byte identical to what's committed):

```bash
uv run python benchmarks/scenarios/scenario1_customer_support.py
uv run python benchmarks/scenarios/scenario2_coding_agent.py
uv run python benchmarks/scenarios/scenario3_research_agent.py
```

Try one yourself:

```bash
uv run wattage report benchmarks/scenarios/scenario2.json --html /tmp/scenario2.html
```

These scenarios (and a fourth, smaller isolated repro — see
`finding1_isolated_test.py`) are what surfaced several real bugs fixed in
`CHANGELOG.md`'s 0.1.1 entry, including the convergence engine's
`reached_success` gate and the `RetrievalCall.chunks` population gap —
every fixed-and-verified claim in that changelog entry traces back to a
trace in this directory, not an unfalsifiable assertion.
