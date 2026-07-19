# CI Integration

`wattage ci` turns a trace into a pass/fail gate, so a pull request that makes your agent measurably more expensive fails the build instead of quietly hitting the invoice a month later.

## Quick start (GitHub Actions)

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
        run: python scripts/run_agent_fixture.py > trace.json   # your own deterministic eval run
      - name: Wattage cost-regression gate
        uses: muhammadfaizanraza/wattage/action@v1
        with:
          source: trace.json
          baseline: .wattage/baseline.json
          quality: quality.json            # optional; enables quality-gated findings
          fail-on: "score_below:80,cost_delta_pct_above:5,any_critical:true"
          pr-comment: "true"
          sarif-out: wattage.sarif
          badge-out: .github/wattage-badge.svg
      - name: Upload SARIF
        if: always()
        uses: github/codeql-action/upload-sarif@v3
        with: { sarif_file: wattage.sarif }
```

Run this only on pull requests, with a `paths:` filter and `concurrency.cancel-in-progress` — running it on every commit floods the PR with noise and (if the optional LLM judge is ever enabled) burns real API budget for no benefit.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Pass — within thresholds vs baseline |
| 1 | Fail — a `fail-on` threshold breached |
| 2 | Config/usage error |
| 3 | Ingestion error — the trace was unparseable, or produced zero sessions |
| 4 | Pricing error — at least one call had no pricing entry; an incomplete cost figure can't honestly gate anything, so this fails loudly instead of silently comparing an undercount |

## The baseline

`.wattage/baseline.json` is a small, committed file: the last **passing** run's metrics, plus a rolling window (7 days by default) of every run for trend purposes. The noise-floor protection here is structural rather than statistical — `last_passing` only ever updates on a run that actually passed the gate, so one flaky bad run can never corrupt what future runs are compared against.

Commit this file. It's what makes `cost_delta_pct_above` meaningful across CI runs on different machines and different days.

## `--fail-on`

Three independent thresholds, any of which can fail the build:

- `score_below:N` — the Token Efficiency score must be at least N.
- `cost_delta_pct_above:N` — total cost must not have increased more than N% versus the baseline's last passing run.
- `any_critical:true` — any single critical-severity finding fails the build outright, regardless of the aggregate score.

## Outputs

- `--pr-comment-out` — a markdown comment (per-detector delta table, the single highest-dollar fix, a provenance footer) suitable for posting via `gh pr comment` or any CI system's PR-comment step.
- `--sarif-out` — each finding as a SARIF result, so it shows up in GitHub's Security tab.
- `--junit-out` — JUnit XML (one testcase per finding, plus an overall gate testcase), for GitLab CI, CircleCI, Jenkins, or anything else that renders JUnit natively.
- `--badge-out` — a Token Efficiency SVG badge for this run, so your README's badge stays current on every merge. Commit the CI job's output back to the repo (e.g. to `.github/wattage-badge.svg`) and point your README's `<img>` at the raw file on your default branch.

## Local dry run

```bash
wattage ci path/to/trace.json --baseline .wattage/baseline.json --fail-on "score_below:80"
echo $?  # 0, 1, 2, 3, or 4 — never silently swallowed
```
