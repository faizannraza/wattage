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


def test_wattage_install_is_pinned_to_this_actions_own_checkout() -> None:
    """The real bug this closes: `uv tool install wattage --quiet` installed
    whatever is currently newest on PyPI, regardless of which action tag a
    workflow pinned (`uses: .../action@v0.1.0`) -- so pinning the action
    didn't actually pin the analysis engine that runs the cost gate.
    github.action_path is this action's own checkout at the pinned ref, so
    installing from there (one directory up from action.yml, the package
    root) ties the two together by construction instead of by a
    manually-maintained version string that could drift."""
    data = yaml.safe_load(ACTION_YML.read_text())
    install_step = next(s for s in data["runs"]["steps"] if s.get("name") == "Install wattage")
    run_command = install_step["run"]

    assert "github.action_path" in run_command
    assert "uv tool install wattage " not in run_command
    assert run_command.strip() != "uv tool install wattage --quiet"


def test_entrypoint_sh_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(ENTRYPOINT_SH)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
