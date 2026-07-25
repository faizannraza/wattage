# Examples

- **`sample_trace.json`** — a small OTLP JSON trace fixture used throughout
  the docs and README as the "try it now" example.
- **`sample_report.golden.txt`** — the exact `wattage report` terminal
  output for `sample_trace.json`; `tests/test_report_integration.py`
  asserts against it, so it's always accurate.
- **`quality.json`** — a `--quality` map in the real shape Wattage expects
  (see `docs/detectors/model_mismatch.md`): `tasks.*.eval_score` feeds the
  quality-factor score gate, `downgrade_evals."tool_select@<model>".pass_rate`
  is what unlocks `model_mismatch` findings. Try it:

  ```bash
  uv run wattage report examples/sample_trace.json --quality examples/quality.json
  ```

- **`instrument_minimal.py`** — for anyone with zero existing OTel
  instrumentation: a real, runnable OpenTelemetry snippet that produces a
  `trace.json` Wattage can read, using OTel's own official OTLP JSON
  encoder. See [`docs/getting-started.md`](../docs/getting-started.md).
  `tests/test_instrument_minimal_example.py` runs it as a real subprocess
  and asserts on the priced output, so it can't silently rot.
