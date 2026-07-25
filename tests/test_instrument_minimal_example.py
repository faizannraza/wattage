"""Runs examples/instrument_minimal.py (the "getting your first trace" doc's
zero-instrumentation snippet) as a real subprocess, then feeds the trace.json
it produces through wattage's real pipeline -- so the example can't silently
rot as the adapter/normalizer/pricing engine evolve.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from wattage.report import build_report

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "examples" / "instrument_minimal.py"


def test_script_produces_a_trace_wattage_prices_correctly(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "wrote trace.json" in result.stdout

    trace_path = tmp_path / "trace.json"
    assert trace_path.exists()

    report = build_report(str(trace_path))

    assert report.token_breakdown["input"] == 1200
    assert report.token_breakdown["output"] == 340
    # claude-sonnet-4-6: $3e-6/input token, $15e-6/output token (pricing.yaml)
    assert report.total_dollars == 1200 * 3.0e-6 + 340 * 15.0e-6
    assert report.unpriced_calls == 0
