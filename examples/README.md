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
