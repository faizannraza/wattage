# CI Integration

`wattage ci` turns a trace into a pass/fail gate, so a pull request that makes your agent measurably more expensive fails the build instead of quietly hitting the invoice a month later.

This needs **two** workflows, not one — a detail that's easy to miss and breaks the whole "tracking" story if skipped. `wattage ci` updates `.wattage/baseline.json` on disk, but a PR runs on an ephemeral, throwaway checkout: whatever it writes vanishes when the job ends. If nothing ever commits the updated file back to your default branch, every future PR compares against the same stale baseline forever, and the rolling window never actually accumulates. The fix is standard and small: gate PRs against the baseline as committed, and update that committed baseline in a separate job that only runs *after* a merge to your default branch.

## 1. The PR gate

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
        uses: faizannraza/wattage/action@main
        with:
          source: trace.json
          baseline: .wattage/baseline.json
          quality: quality.json            # optional; enables quality-gated findings
          fail-on: "score_below:80,cost_delta_pct_above:5,any_critical:true"
          pr-comment: "true"
          sarif-out: wattage.sarif
      - name: Upload SARIF
        if: always()
        uses: github/codeql-action/upload-sarif@v3
        with: { sarif_file: wattage.sarif }
```

Run this only on pull requests, with a `paths:` filter and `concurrency.cancel-in-progress` — running it on every commit floods the PR with noise and (if the optional LLM judge is ever enabled) burns real API budget for no benefit. `uses: faizannraza/wattage/action@main` tracks the Action's default branch; pin to a released tag (`@v1`, once one exists) once you want a stable, immovable reference.

## 2. The baseline updater

```yaml
# .github/workflows/wattage-baseline.yml
name: Wattage baseline
on:
  push:
    branches: [main]
    paths: ["agents/**", "prompts/**", "src/**"]
permissions:
  contents: write
jobs:
  update-baseline:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Generate trace fixture
        run: python scripts/run_agent_fixture.py > trace.json
      - name: Update Wattage baseline
        uses: faizannraza/wattage/action@main
        with:
          source: trace.json
          baseline: .wattage/baseline.json
          pr-comment: "false"
          badge-out: .github/wattage-badge.svg
      - name: Commit updated baseline
        run: |
          git config user.name "wattage-bot"
          git config user.email "wattage-bot@users.noreply.github.com"
          git add .wattage/baseline.json .github/wattage-badge.svg
          git diff --cached --quiet || git commit -m "wattage: update cost baseline [skip ci]"
          git push
```

This only runs on pushes to your default branch (i.e. after a PR merges), so it always records the real, merged state — never an in-progress PR's numbers — and it's what keeps the badge in your README current too. `[skip ci]` in the commit message stops this from re-triggering your own build pipelines in a loop; adjust the marker to whatever your CI provider honors.

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

It only stays meaningful if something commits it after each merge — that's what workflow 2 above does. Start the repo off with an initial baseline (`wattage ci trace.json` locally, once, against a known-good trace, then commit the `.wattage/baseline.json` it writes) so the very first PR has something real to compare against.

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
