import xml.etree.ElementTree as ET

from wattage.models import Finding, QualityRisk, Report, Score, Severity
from wattage.render.junit import render_junit


def _report(findings: list[Finding]) -> Report:
    return Report(
        trace_source="t.json",
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


def _finding(detector_id: str, severity: Severity, dollars: float = 0.01) -> Finding:
    return Finding(
        id=detector_id,
        severity=severity,
        wasted_tokens=10,
        wasted_dollars=dollars,
        quality_risk=QualityRisk.none,
        evidence="something happened",
        fix="do the fix",
    )


def test_output_is_valid_xml() -> None:
    xml_str = render_junit(_report([_finding("prefix_churn", Severity.high)]))
    root = ET.fromstring(xml_str)  # raises on invalid XML
    assert root.tag == "testsuite"


def test_high_and_critical_findings_are_failures() -> None:
    report = _report(
        [_finding("prefix_churn", Severity.high), _finding("cache_gap", Severity.critical)]
    )
    xml_str = render_junit(report)
    root = ET.fromstring(xml_str)
    failing_cases = [tc for tc in root.findall("testcase") if tc.find("failure") is not None]
    # 2 finding failures + 0 ci-gate failure (no reasons passed) = 2
    assert len(failing_cases) == 2
    assert root.get("failures") == "2"


def test_low_and_medium_findings_do_not_fail() -> None:
    report = _report(
        [_finding("verbosity", Severity.low), _finding("reasoning_overspend", Severity.medium)]
    )
    xml_str = render_junit(report)
    root = ET.fromstring(xml_str)
    failing_cases = [tc for tc in root.findall("testcase") if tc.find("failure") is not None]
    assert len(failing_cases) == 0
    assert root.get("failures") == "0"


def test_ci_gate_failure_reasons_produce_a_failing_gate_testcase() -> None:
    xml_str = render_junit(_report([]), ci_reasons=["score 50 is below threshold 80"])
    root = ET.fromstring(xml_str)
    gate_case = next(
        tc for tc in root.findall("testcase") if tc.get("classname") == "wattage.ci_gate"
    )
    failure = gate_case.find("failure")
    assert failure is not None
    assert "score 50" in failure.get("message", "")


def test_test_count_matches_gate_plus_findings() -> None:
    report = _report([_finding("prefix_churn", Severity.high), _finding("verbosity", Severity.low)])
    xml_str = render_junit(report)
    root = ET.fromstring(xml_str)
    assert root.get("tests") == "3"  # 1 gate + 2 findings


def test_double_quotes_in_evidence_and_fix_text_do_not_break_the_xml() -> None:
    """The real bug this closes: finding evidence/fix text is derived from
    trace content -- untrusted input on the `wattage ci` path -- and used
    to land inside double-quoted XML attributes. escape() alone only
    handles &/</> , not a literal '"', so a quote in the text used to
    terminate the attribute early and produce invalid XML a JUnit-consuming
    CI system couldn't parse."""
    finding = Finding(
        id="verbosity",
        severity=Severity.high,
        wasted_tokens=10,
        wasted_dollars=1.23,
        quality_risk=QualityRisk.none,
        evidence='tool call with "quoted" arg and <angle> & amp',
        fix='trim the "weird" tokens & <stuff>',
    )
    report = _report([finding])

    xml_str = render_junit(report, ci_reasons=['score is "bad" & <weird>'])

    root = ET.fromstring(xml_str)  # raises on invalid XML
    gate_case = next(
        tc for tc in root.findall("testcase") if tc.get("classname") == "wattage.ci_gate"
    )
    assert gate_case.find("failure").get("message") == 'score is "bad" & <weird>'
    finding_case = next(
        tc for tc in root.findall("testcase") if tc.get("classname") == "wattage.verbosity"
    )
    assert '"quoted"' in finding_case.get("name")
    assert '"weird"' in finding_case.find("failure").get("message")
