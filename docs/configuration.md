# Configuration

Every threshold in this doc has a sensible default — you don't need a config file at all to get useful output. `wattage.yaml` exists for the cases where the defaults don't fit: a noisier detector you want to quiet down, a different convergence sensitivity, a stricter CI gate.

## Where it's read from

- With no `--config` flag, every command (`report`, `score`, `badge`, `ci`) looks for `./wattage.yaml` in the current working directory. If it's not there, you get plain defaults — a config file is optional, not required.
- `--config path/to/file.yaml` loads a specific file instead, on any command.
- An explicit `--config` path that doesn't exist, isn't valid YAML, or doesn't match the schema below is a hard error (exit code 2) — asking for a specific file and having it silently ignored would hide a real mistake. A *missing* file with no explicit `--config` is not an error; that's the normal unconfigured case.

You only need to specify the fields you want to override — anything you leave out keeps its default.

## Example

```yaml
# wattage.yaml
detectors:
  verbosity:
    expected_output_ceiling: 2000   # this codebase's steps genuinely run long
  redundant_tool_calls:
    enabled: false                  # too noisy for this agent's polling pattern

quality:
  target: 0.85

ci:
  fail_on:
    score_below: 75
    cost_delta_pct_above: 10
```

## Reference

### `detectors.*`

Each detector has its own `enabled: bool` (default `true`) plus whatever thresholds it uses — see each detector's own page under [Detectors](detectors/index.md) for what each threshold means and why its default was chosen. The keys match the detector IDs shown in a report's findings table:

| Key | Notable fields (defaults) |
|---|---|
| `prefix_churn` | `high_severity_ratio: 0.30` |
| `cache_gap` | *(no tunable thresholds)* |
| `verbosity` | `expected_output_ceiling: 1000`, `high_severity_multiplier: 3.0` |
| `redundant_tool_calls` | `window: 5`, `fuzzy: true`, `exempt_tools: [poll_status, wait, healthcheck]` |
| `nonconvergence` | `min_iterations: 3`, `theta_prog: 0.25`, `consecutive_k: 3`, `oscillation_threshold: 0.6`, `stall_evidence_threshold: 0.15`, `stall_state_threshold: 0.15`, `stall_growth_threshold: 0.5`, `osc_window: 6`, `max_period: 4`, `weights: {E: 0.40, S: 0.20, P: 0.20, O: 0.15, G: 0.05}`, `exempt_tools`, `embed: local`, `judge: off` |
| `retrieval_thrash` | `relevance_threshold: 0.35`, `max_iterations_soft: 4` |
| `model_mismatch` | `downgrade_candidates: {anthropic: claude-haiku-4-5, openai: gpt-5.6-luna}`, `simple_output_ceiling: 150`, `require_quality_map: true`, `min_downgrade_pass_rate: 0.90` |
| `reasoning_overspend` | `expected_reasoning_ceiling: 500`, `simple_output_ceiling: 150` |

See [The Convergence Engine](convergence.md) for what `nonconvergence`'s E/S/P/O/G weights and thresholds actually mean.

### `quality`

| Field | Default | Meaning |
|---|---|---|
| `target` | `0.90` | The eval score `--quality`'s `tasks.*.eval_score` values are compared against when computing the quality factor that scales your Token Efficiency grade. |

### `ci`

| Field | Default | Meaning |
|---|---|---|
| `baseline_path` | `.wattage/baseline.json` | Default baseline location if `--baseline` isn't passed. |
| `rolling_window_days` | `7` | How long the baseline's trend history is kept. |
| `fail_on.score_below` | `80` | Fail if the Token Efficiency score drops below this. |
| `fail_on.cost_delta_pct_above` | `5.0` | Fail if total cost increased more than this percent vs. the baseline's last passing run. |
| `fail_on.any_critical` | `true` | Fail on any single critical-severity finding, regardless of the aggregate score. |
| `badge_out` / `sarif_out` / `pr_comment_out` | `null` | Default output paths, if you don't want to pass `--badge-out`/`--sarif-out`/`--pr-comment-out` on every invocation. |

Any of these can also be overridden per-invocation with the matching CLI flag (e.g. `--fail-on "score_below:75"`) — an explicit flag always wins over both the config file and the built-in default.
