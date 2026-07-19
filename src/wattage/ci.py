"""wattage ci (doc §11): the cost-regression gate.

Exit codes exactly per §11.3:
  0 pass
  1 fail — a fail-on threshold breached
  2 config/usage error
  3 ingestion error — unparseable *or empty* trace (the doc names both)
  4 pricing error — at least one call the pricing engine couldn't price;
    an incomplete cost figure can't honestly gate anything, so this fails
    loudly rather than silently comparing against an undercount.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from wattage.baseline import (
    Baseline,
    cost_delta_pct,
    load_baseline,
    record_run,
    save_baseline,
)
from wattage.config import CIFailOnConfig, WattageConfig
from wattage.models import Report, Severity
from wattage.report import build_trace_and_report

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_CONFIG_ERROR = 2
EXIT_INGESTION_ERROR = 3
EXIT_PRICING_ERROR = 4


class CIConfigError(Exception):
    """Exit code 2."""


@dataclass
class CIResult:
    exit_code: int
    report: Report | None = None
    baseline: Baseline | None = None
    reasons: list[str] = field(default_factory=list)


def parse_fail_on(spec: str) -> CIFailOnConfig:
    """Parses "key:value,key:value" — the doc's own action.yml example format,
    e.g. "score_below:80,cost_delta_pct_above:5,any_critical:true"."""
    values: dict[str, str] = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise CIConfigError(f"invalid --fail-on clause (expected key:value): {part!r}")
        key, _, value = part.partition(":")
        values[key.strip()] = value.strip()

    defaults = CIFailOnConfig()
    try:
        score_below = (
            int(values["score_below"]) if "score_below" in values else defaults.score_below
        )
        cost_delta_pct_above = (
            float(values["cost_delta_pct_above"])
            if "cost_delta_pct_above" in values
            else defaults.cost_delta_pct_above
        )
    except ValueError as exc:
        raise CIConfigError(f"invalid --fail-on numeric value: {exc}") from exc
    any_critical = (
        values["any_critical"].strip().lower() in ("true", "1", "yes")
        if "any_critical" in values
        else defaults.any_critical
    )
    return CIFailOnConfig(
        score_below=score_below,
        cost_delta_pct_above=cost_delta_pct_above,
        any_critical=any_critical,
    )


def evaluate_fail_on(report: Report, baseline: Baseline, fail_on: CIFailOnConfig) -> list[str]:
    reasons = []
    if fail_on.score_below is not None and report.score.efficiency < fail_on.score_below:
        reasons.append(f"score {report.score.efficiency} is below threshold {fail_on.score_below}")
    if fail_on.cost_delta_pct_above is not None:
        delta = cost_delta_pct(report, baseline)
        if delta is not None and delta > fail_on.cost_delta_pct_above:
            reasons.append(
                f"cost increased {delta:.1f}% vs baseline, above threshold "
                f"{fail_on.cost_delta_pct_above}%"
            )
    if fail_on.any_critical and any(f.severity == Severity.critical for f in report.findings):
        reasons.append("at least one critical-severity finding")
    return reasons


def run_ci(
    source: str,
    baseline_path: str | None = None,
    pricing_override: str | None = None,
    quality_file: str | None = None,
    fail_on: CIFailOnConfig | None = None,
    config: WattageConfig | None = None,
    update_baseline: bool = True,
) -> CIResult:
    config = config or WattageConfig()
    fail_on = fail_on or config.ci.fail_on
    resolved_baseline_path = baseline_path or config.ci.baseline_path

    try:
        trace, report = build_trace_and_report(
            source,
            pricing_override=pricing_override,
            config=config,
            quality_file=quality_file,
        )
    except (OSError, json.JSONDecodeError) as exc:
        return CIResult(exit_code=EXIT_INGESTION_ERROR, reasons=[str(exc)])

    if not trace.sessions:
        return CIResult(
            exit_code=EXIT_INGESTION_ERROR,
            reasons=[f"'{source}' produced zero sessions (empty or unparseable trace)"],
        )

    if report.unpriced_calls > 0:
        return CIResult(
            exit_code=EXIT_PRICING_ERROR,
            report=report,
            reasons=[
                f"{report.unpriced_calls} call(s) had no pricing entry — "
                "supply a --pricing override or the cost comparison would be an undercount"
            ],
        )

    # The baseline as it stood *before* this run — what this run was actually
    # compared against, and what render_pr_comment/render's delta table
    # should diff against. Comparing against the post-update baseline would
    # (once this run itself becomes last_passing) show the run diffed
    # against itself: always "no change".
    baseline_before = load_baseline(resolved_baseline_path)
    reasons = evaluate_fail_on(report, baseline_before, fail_on)
    passed = not reasons
    exit_code = EXIT_PASS if passed else EXIT_FAIL

    if update_baseline:
        updated = record_run(
            baseline_before, report, passed=passed, window_days=config.ci.rolling_window_days
        )
        save_baseline(resolved_baseline_path, updated)

    return CIResult(exit_code=exit_code, report=report, baseline=baseline_before, reasons=reasons)
