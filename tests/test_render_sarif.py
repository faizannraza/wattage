import json

from wattage.models import Finding, QualityRisk, Report, Score, Severity
from wattage.render.sarif import render_sarif


def _report(findings: list[Finding], trace_source: str = "trace.json") -> Report:
    return Report(
        trace_source=trace_source,
        total_dollars=1.0,
        token_breakdown={},
        findings=findings,
        score=Score(
            efficiency=80,
            grade="B",
            waste_ratio=0.1,
            quality_factor=1.0,
            quality_measured=False,
            recoverable_dollars=sum(f.wasted_dollars for f in findings),
        ),
        pricing_version="v",
        generated_at="2026-01-01T00:00:00Z",
    )


def _finding(
    detector_id: str,
    severity: Severity,
    location: str | None = None,
    quality_risk: QualityRisk = QualityRisk.none,
) -> Finding:
    return Finding(
        id=detector_id,
        severity=severity,
        wasted_tokens=100,
        wasted_dollars=0.05,
        quality_risk=quality_risk,
        evidence="something happened",
        fix="do the fix",
        location=location,
    )


def test_output_is_valid_json_matching_sarif_2_1_0() -> None:
    sarif = json.loads(render_sarif(_report([_finding("prefix_churn", Severity.high)])))
    assert sarif["version"] == "2.1.0"
    assert len(sarif["runs"]) == 1
    assert sarif["runs"][0]["tool"]["driver"]["name"] == "wattage"


def test_severity_maps_to_sarif_level() -> None:
    report = _report(
        [
            _finding("a", Severity.critical),
            _finding("b", Severity.high),
            _finding("c", Severity.medium),
            _finding("d", Severity.low),
            _finding("e", Severity.info),
        ]
    )
    results = json.loads(render_sarif(report))["runs"][0]["results"]
    levels = {r["ruleId"]: r["level"] for r in results}
    assert levels["a"] == "error"
    assert levels["b"] == "error"
    assert levels["c"] == "warning"
    assert levels["d"] == "note"
    assert levels["e"] == "note"


def test_location_falls_back_to_trace_source_when_finding_has_none() -> None:
    report = _report([_finding("prefix_churn", Severity.high)], trace_source="my_trace.json")
    result = json.loads(render_sarif(report))["runs"][0]["results"][0]
    uri = result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    assert uri == "my_trace.json"


def test_location_uses_findings_own_location_when_present() -> None:
    report = _report([_finding("prefix_churn", Severity.high, location="config/prompt.yaml")])
    result = json.loads(render_sarif(report))["runs"][0]["results"][0]
    uri = result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    assert uri == "config/prompt.yaml"


def test_rules_are_deduplicated_across_repeated_findings() -> None:
    report = _report(
        [_finding("prefix_churn", Severity.high), _finding("prefix_churn", Severity.medium)]
    )
    rules = json.loads(render_sarif(report))["runs"][0]["tool"]["driver"]["rules"]
    assert [r["id"] for r in rules] == ["prefix_churn"]


def test_properties_carry_the_real_wasted_amounts() -> None:
    report = _report([_finding("prefix_churn", Severity.high)])
    result = json.loads(render_sarif(report))["runs"][0]["results"][0]
    assert result["properties"]["wasted_tokens"] == 100
    assert result["properties"]["wasted_dollars"] == 0.05
