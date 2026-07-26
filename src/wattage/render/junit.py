"""JUnit XML (doc §11.6): one testcase per finding plus an overall CI-gate
testcase, so generic CI systems (GitLab, CircleCI, Jenkins) can render
wattage results natively without needing GitHub-specific integration.
"""

from __future__ import annotations

import re
from xml.sax.saxutils import escape, quoteattr

from wattage.models import Report, Severity

_FAILING_SEVERITIES = {Severity.high, Severity.critical}

# XML 1.0 forbids these control characters outright (tab/LF/CR are the only
# ones under 0x20 that are legal) -- quoteattr()/escape() only handle &/</>/"
# and never touch raw bytes, so a control character surviving in trace
# content (e.g. an ANSI escape sequence in a tool name/result) would make
# the whole file fail to parse, not just corrupt one element.
_ILLEGAL_XML_CHARS_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _sanitize(text: str) -> str:
    return _ILLEGAL_XML_CHARS_RE.sub("", text)


def render_junit(report: Report, ci_reasons: list[str] | None = None) -> str:
    """`escape()` alone only handles &/</> -- safe inside element text, but
    every value below also lands inside a double-quoted attribute, and
    finding evidence/fix text originates from trace content (untrusted
    input in the `wattage ci` path), so a literal `"` must be escaped too.
    `quoteattr()` escapes and quotes in one step, so it's used everywhere a
    value is written as an attribute value.
    """
    ci_reasons = ci_reasons or []
    testcases = []

    gate_name = quoteattr(f"Token Efficiency: {report.score.grade} ({report.score.efficiency})")
    if ci_reasons:
        message_text = _sanitize("; ".join(ci_reasons))
        message_attr = quoteattr(message_text)
        testcases.append(
            f'<testcase classname="wattage.ci_gate" name={gate_name}>'
            f"<failure message={message_attr}>{escape(message_text)}</failure></testcase>"
        )
    else:
        testcases.append(f'<testcase classname="wattage.ci_gate" name={gate_name}/>')

    for i, finding in enumerate(report.findings):
        name = quoteattr(_sanitize(f"{finding.id}[{i}]: {finding.evidence[:80]}"))
        classname = f"wattage.{finding.id}"
        if finding.severity in _FAILING_SEVERITIES:
            message_text = _sanitize(f"${finding.wasted_dollars:.4f} wasted — {finding.fix}")
            message_attr = quoteattr(message_text)
            testcases.append(
                f'<testcase classname="{classname}" name={name}>'
                f"<failure message={message_attr}>{escape(message_text)}</failure></testcase>"
            )
        else:
            testcases.append(f'<testcase classname="{classname}" name={name}/>')

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
