"""Markdown PR comment (doc §11.4): per-detector delta table, top fix,
provenance footer.

Only detectors that produced waste in the current run *or* the baseline get
a table row — a row of "ok" for every detector that never fires (8+ of them
now) would be noise a reviewer has to scan past, not a decision-driving
signal (doc §3.5's own design principle: "every output ends in a
decision"). Detectors with zero waste in both runs are implicitly fine by
omission.
"""

from __future__ import annotations

from wattage.baseline import Baseline, DetectorDelta, diff_against_baseline
from wattage.models import Report


def _fmt_tokens(n: int) -> str:
    if n == 0:
        return "0"
    if n >= 1000:
        return f"{n / 1000:.1f}k tok"
    return f"{n} tok"


def _delta_cell(delta: DetectorDelta) -> tuple[str, str]:
    if delta.is_new:
        return "▲ new", f"${delta.current_dollars:.4f}"
    pct = delta.pct_change
    if pct is None:
        return "—", f"${delta.current_dollars:.4f}"
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "—")
    sign = "+" if pct >= 0 else ""
    return f"{arrow} {sign}{pct:.0f}%", f"${delta.current_dollars:.4f}"


def render_pr_comment(report: Report, baseline: Baseline) -> str:
    score = report.score

    baseline_efficiency = baseline.last_passing.efficiency if baseline.last_passing else None
    if baseline_efficiency is not None:
        score_delta = score.efficiency - baseline_efficiency
        arrow = "▲" if score_delta > 0 else ("▼" if score_delta < 0 else "—")
        header_suffix = f"  {arrow} {abs(score_delta)} vs baseline"
    else:
        header_suffix = "  (no baseline yet)"

    lines = [
        f"### ⚡ Wattage — Token Efficiency: {score.grade} ({score.efficiency}){header_suffix}",
        "",
    ]

    if score.monthly_projection is not None:
        lines.append(
            f"Estimated recoverable waste: **${score.recoverable_dollars:.2f}/run "
            f"(~${score.monthly_projection:,.0f}/mo)**"
        )
    else:
        lines.append(f"Estimated recoverable waste: **${score.recoverable_dollars:.4f}/run**")
    lines.append("")

    deltas = [
        d for d in diff_against_baseline(report, baseline) if d.current_tokens or d.baseline_tokens
    ]
    if deltas:
        lines.append("| Detector | This run | Baseline | Δ | $ waste |")
        lines.append("|---|---|---|---|---|")
        for delta in deltas:
            delta_col, waste_col = _delta_cell(delta)
            this_run = _fmt_tokens(delta.current_tokens)
            baseline_col = _fmt_tokens(delta.baseline_tokens)
            lines.append(
                f"| {delta.detector_id} | {this_run} | {baseline_col} | {delta_col} | {waste_col} |"
            )
        lines.append("")

    if report.findings:
        top = max(report.findings, key=lambda f: f.wasted_dollars)
        quality_note = " (quality-neutral)" if top.quality_risk.value == "none" else ""
        lines.append(
            f"**Top fix:** {top.fix} → ~${top.wasted_dollars:.4f}/run recoverable{quality_note}."
        )
        lines.append("")

    quality_footer = (
        "quality: measured"
        if score.quality_measured
        else "quality: unmeasured (add quality.json to gate model-downgrade findings)"
    )
    lines.append(f"<sub>pricing: {report.pricing_version} · {quality_footer}</sub>")

    return "\n".join(lines)
