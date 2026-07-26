"""load_config() (doc §9.6): wattage.yaml actually loads.

Confirmed by a real bug this closes: config.py's own docstring called
itself "wattage.yaml config schema" and CONTRIBUTING.md told detector
authors users could turn a detector off "in wattage.yaml" -- but nothing
anywhere ever read such a file. Every command constructed a bare
WattageConfig() with defaults, unconditionally. These tests exercise the
real load path, not just schema defaults.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wattage.config import DEFAULT_CONFIG_FILENAME, WattageConfig, WattageConfigError, load_config


def test_no_explicit_path_and_no_file_in_cwd_returns_plain_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A config file is optional, not required -- no file at all, with no
    explicit path given, is the normal unconfigured case, not an error."""
    monkeypatch.chdir(tmp_path)
    assert load_config() == WattageConfig()


def test_explicit_path_loads_and_merges_with_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "custom.yaml"
    config_path.write_text(
        "detectors:\n"
        "  verbosity:\n"
        "    expected_output_ceiling: 500\n"
        "  redundant_tool_calls:\n"
        "    enabled: false\n"
    )

    cfg = load_config(str(config_path))

    assert cfg.detectors.verbosity.expected_output_ceiling == 500
    assert cfg.detectors.redundant_tool_calls.enabled is False
    # Untouched sections keep their real defaults -- a partial override
    # file must not blank out everything else.
    assert cfg.detectors.prefix_churn.high_severity_ratio == 0.30
    assert cfg.ci.rolling_window_days == 7


def test_auto_discovers_wattage_yaml_in_the_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / DEFAULT_CONFIG_FILENAME).write_text("quality:\n  target: 0.75\n")
    monkeypatch.chdir(tmp_path)

    cfg = load_config()

    assert cfg.quality.target == 0.75


def test_explicit_path_missing_raises_clearly(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.yaml"
    with pytest.raises(WattageConfigError, match="could not read config file"):
        load_config(str(missing))


def test_invalid_yaml_raises_clearly(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("not: valid: yaml: [")
    with pytest.raises(WattageConfigError, match="invalid YAML"):
        load_config(str(bad))


def test_non_mapping_top_level_raises_clearly(tmp_path: Path) -> None:
    bad = tmp_path / "list.yaml"
    bad.write_text("- just\n- a\n- list\n")
    with pytest.raises(WattageConfigError, match="must be a YAML mapping"):
        load_config(str(bad))


def test_schema_violation_raises_clearly(tmp_path: Path) -> None:
    bad = tmp_path / "bad_schema.yaml"
    bad.write_text('detectors:\n  verbosity:\n    expected_output_ceiling: "not a number"\n')
    with pytest.raises(WattageConfigError, match="invalid config"):
        load_config(str(bad))


def test_empty_file_returns_plain_defaults(tmp_path: Path) -> None:
    empty = tmp_path / "empty.yaml"
    empty.write_text("")
    assert load_config(str(empty)) == WattageConfig()


def test_unrecognized_key_raises_clearly_instead_of_silently_ignored(tmp_path: Path) -> None:
    """The real bug this closes: a typo'd key (e.g.
    expected_output_ceilling, or a misspelled detector name like
    cache_gapp) used to load with no error at all -- pydantic's default
    extra="ignore" behavior -- silently keeping every default untouched
    while the user believes they configured something. This directly
    contradicted docs/configuration.md's own documented claim that a
    schema violation is a hard error (exit code 2)."""
    bad = tmp_path / "typo.yaml"
    bad.write_text(
        "detectors:\n"
        "  verbosity:\n"
        "    expected_output_ceilling: 5\n"
        "  cache_gapp:\n"
        "    enabled: false\n"
    )
    with pytest.raises(WattageConfigError, match="invalid config"):
        load_config(str(bad))
