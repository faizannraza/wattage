"""SARIF (doc §11.5): each finding as a code-scanning result, so it shows up
in GitHub's Security tab.

Findings don't currently carry a source-file location — no detector
populates Finding.location, since they operate on trace data, not source
code — so results fall back to the trace source file itself at line 1: an
honest "this is what was analyzed", not a fabricated line number.
"""

from __future__ import annotations

import json
from typing import Any

from wattage.models import Report, Severity

_LEVEL_BY_SEVERITY = {
    Severity.critical: "error",
    Severity.high: "error",
    Severity.medium: "warning",
    Severity.low: "note",
    Severity.info: "note",
}


def render_sarif(report: Report, tool_version: str = "0.1.0") -> str:
    rule_ids = sorted({f.id for f in report.findings})
    rules = [{"id": rule_id, "shortDescription": {"text": rule_id}} for rule_id in rule_ids]

    results: list[dict[str, Any]] = []
    for finding in report.findings:
        uri = finding.location or report.trace_source
        results.append(
            {
                "ruleId": finding.id,
                "level": _LEVEL_BY_SEVERITY.get(finding.severity, "warning"),
                "message": {"text": f"{finding.evidence} Fix: {finding.fix}"},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": uri},
                            "region": {"startLine": 1},
                        }
                    }
                ],
                "properties": {
                    "wasted_tokens": finding.wasted_tokens,
                    "wasted_dollars": finding.wasted_dollars,
                    "quality_risk": finding.quality_risk.value,
                },
            }
        )

    sarif = {
        "$schema": (
            "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/"
            "sarif-schema-2.1.0.json"
        ),
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "wattage",
                        "version": tool_version,
                        "informationUri": "https://github.com/muhammadfaizanraza/wattage",
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(sarif, indent=2)
