"""JUnit XML (doc §11.6): one testcase per finding plus an overall CI-gate
testcase, so generic CI systems (GitLab, CircleCI, Jenkins) can render
wattage results natively without needing GitHub-specific integration.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from wattage.models import Report, Severity

_FAILING_SEVERITIES = {Severity.high, Severity.critical}


def render_junit(report: Report, ci_reasons: list[str] | None = None) -> str:
    ci_reasons = ci_reasons or []
    testcases = []

    gate_name = escape(f"Token Efficiency: {report.score.grade} ({report.score.efficiency})")
    if ci_reasons:
        message = escape("; ".join(ci_reasons))
        testcases.append(
            f'<testcase classname="wattage.ci_gate" name="{gate_name}">'
            f'<failure message="{message}">{message}</failure></testcase>'
        )
    else:
        testcases.append(f'<testcase classname="wattage.ci_gate" name="{gate_name}"/>')

    for i, finding in enumerate(report.findings):
        name = escape(f"{finding.id}[{i}]: {finding.evidence[:80]}")
        classname = f"wattage.{finding.id}"
        if finding.severity in _FAILING_SEVERITIES:
            message = escape(f"${finding.wasted_dollars:.4f} wasted — {finding.fix}")
            testcases.append(
                f'<testcase classname="{classname}" name="{name}">'
                f'<failure message="{message}">{message}</failure></testcase>'
            )
        else:
            testcases.append(f'<testcase classname="{classname}" name="{name}"/>')

    failures = sum(1 for f in report.findings if f.severity in _FAILING_SEVERITIES) + (
        1 if ci_reasons else 0
    )
    total = len(testcases)
    body = "\n  ".join(testcases)

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<testsuite name="wattage" tests="{total}" failures="{failures}" time="0">\n  '
        f"{body}\n"
        "</testsuite>\n"
    )
