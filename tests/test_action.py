"""Lightweight sanity checks for the GitHub Action definition — catches
accidental breakage of action.yml's structure. The action's actual runtime
behavior (installing wattage, posting a PR comment) can only be verified
against a real GitHub Actions run; entrypoint.sh's own argument-building and
exit-code-propagation logic was manually run against the real CLI (both a
passing and a failing case) during development, not just eyeballed.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
ACTION_YML = REPO_ROOT / "action" / "action.yml"
ENTRYPOINT_SH = REPO_ROOT / "action" / "entrypoint.sh"


def test_action_yml_is_valid_yaml_with_expected_shape() -> None:
    data = yaml.safe_load(ACTION_YML.read_text())
    assert data["runs"]["using"] == "composite"
    assert "source" in data["inputs"]
    assert data["inputs"]["source"]["required"] is True
    assert "badge-out" in data["inputs"]
    assert "exit-code" in data["outputs"]


def test_entrypoint_is_executable_and_referenced_correctly() -> None:
    assert ENTRYPOINT_SH.exists()
    assert os.access(ENTRYPOINT_SH, os.X_OK)
    data = yaml.safe_load(ACTION_YML.read_text())
    run_step = next(s for s in data["runs"]["steps"] if s.get("id") == "run")
    assert "entrypoint.sh" in run_step["run"]


def test_entrypoint_sh_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(ENTRYPOINT_SH)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
