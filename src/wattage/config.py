"""wattage.yaml config schema (doc §9.6)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class _StrictModel(BaseModel):
    """A typo'd or unrecognized key in wattage.yaml must be a hard error,
    not silently ignored -- pydantic's own default (extra="ignore") would
    otherwise let a user believe they've overridden a threshold (e.g.
    ci.fail_on.score_below misspelled) while every command quietly keeps
    running on the untouched default, exactly the "silently plausible
    wrong behavior" this project exists to avoid. Every config model
    below inherits this instead of BaseModel directly."""

    model_config = ConfigDict(extra="forbid")


class PrefixChurnConfig(_StrictModel):
    enabled: bool = True
    # A finding's severity is "high" once its share of the task's total cost
    # crosses this ratio (doc §4.1: "severity from resent_dollars/session_dollars").
    high_severity_ratio: float = 0.30


class CacheGapConfig(_StrictModel):
    enabled: bool = True


class VerbosityConfig(_StrictModel):
    enabled: bool = True
    # Calls with no max_tokens cap that generate more than this many output
    # tokens are flagged. A single global ceiling, not doc §9.6's per-task-type
    # bands (extract/classify/draft) — those need task-type classification,
    # which doesn't exist yet; revisit once it does.
    expected_output_ceiling: int = 1000
    high_severity_multiplier: float = 3.0


class RedundantToolCallsConfig(_StrictModel):
    enabled: bool = True
    window: int = 5
    fuzzy: bool = True
    exempt_tools: list[str] = Field(default_factory=lambda: ["poll_status", "wait", "healthcheck"])


class ConvergenceWeightsConfig(_StrictModel):
    """Field names match doc §5.3's notation (E/S/P/O/G) exactly, on purpose."""

    E: float = 0.40
    S: float = 0.20
    P: float = 0.20
    O: float = 0.15  # noqa: E741 (ambiguous-with-zero; matches doc notation deliberately)
    G: float = 0.05


class NonConvergenceConfig(_StrictModel):
    enabled: bool = True
    min_iterations: int = 3
    theta_prog: float = 0.25
    consecutive_k: int = 3
    oscillation_threshold: float = 0.6
    stall_evidence_threshold: float = 0.15
    stall_state_threshold: float = 0.15
    stall_growth_threshold: float = 0.5
    osc_window: int = 6
    max_period: int = 4
    weights: ConvergenceWeightsConfig = Field(default_factory=ConvergenceWeightsConfig)
    exempt_tools: list[str] = Field(default_factory=lambda: ["poll_status", "wait", "healthcheck"])
    embed: str = "local"
    judge: str = "off"


class RetrievalThrashConfig(_StrictModel):
    enabled: bool = True
    relevance_threshold: float = 0.35
    max_iterations_soft: int = 4


class ModelMismatchConfig(_StrictModel):
    enabled: bool = True
    # provider -> candidate model id, defaulting to the vendored registry's
    # cheapest known model per provider (doc §9.6's "[haiku-class]").
    downgrade_candidates: dict[str, str] = Field(
        default_factory=lambda: {"anthropic": "claude-haiku-4-5", "openai": "gpt-5.6-luna"}
    )
    # A call looks like a plain tool-selection step (candidate for downgrade)
    # when its own output is this small or smaller.
    simple_output_ceiling: int = 150
    # doc's own default: never recommend a downgrade without evidence. With
    # this on, the detector produces nothing at all unless a --quality map's
    # downgrade_evals confirms the candidate model passes.
    require_quality_map: bool = True
    min_downgrade_pass_rate: float = 0.90


class ReasoningOverspendConfig(_StrictModel):
    enabled: bool = True
    expected_reasoning_ceiling: int = 500
    simple_output_ceiling: int = 150


class DetectorsConfig(_StrictModel):
    prefix_churn: PrefixChurnConfig = Field(default_factory=PrefixChurnConfig)
    cache_gap: CacheGapConfig = Field(default_factory=CacheGapConfig)
    verbosity: VerbosityConfig = Field(default_factory=VerbosityConfig)
    redundant_tool_calls: RedundantToolCallsConfig = Field(default_factory=RedundantToolCallsConfig)
    nonconvergence: NonConvergenceConfig = Field(default_factory=NonConvergenceConfig)
    retrieval_thrash: RetrievalThrashConfig = Field(default_factory=RetrievalThrashConfig)
    model_mismatch: ModelMismatchConfig = Field(default_factory=ModelMismatchConfig)
    reasoning_overspend: ReasoningOverspendConfig = Field(default_factory=ReasoningOverspendConfig)


class QualityConfig(_StrictModel):
    target: float = 0.90


class CIFailOnConfig(_StrictModel):
    score_below: int | None = 80
    cost_delta_pct_above: float | None = 5.0
    any_critical: bool = True


class CIConfig(_StrictModel):
    baseline_path: str = ".wattage/baseline.json"
    rolling_window_days: int = 7
    fail_on: CIFailOnConfig = Field(default_factory=CIFailOnConfig)
    # Default output paths, so a CI job doesn't have to repeat
    # --badge-out/--sarif-out/--pr-comment-out on every wattage ci
    # invocation -- an explicit CLI flag always overrides these.
    badge_out: str | None = None
    sarif_out: str | None = None
    pr_comment_out: str | None = None


class WattageConfig(_StrictModel):
    detectors: DetectorsConfig = Field(default_factory=DetectorsConfig)
    quality: QualityConfig = Field(default_factory=QualityConfig)
    ci: CIConfig = Field(default_factory=CIConfig)


class WattageConfigError(Exception):
    """A wattage.yaml file exists but couldn't be read, parsed, or
    validated against the schema above."""


DEFAULT_CONFIG_FILENAME = "wattage.yaml"


def load_config(path: str | None = None) -> WattageConfig:
    """Load a wattage.yaml config file into a WattageConfig.

    An explicit `path` always wins, and raises WattageConfigError if it
    can't be read/parsed/validated -- asking for a specific file and
    having it silently ignored would hide a real mistake. With no
    explicit path, this looks for `./wattage.yaml` in the current working
    directory (the convention every command assumes for `.wattage/
    baseline.json` too); if that's absent, a config file is optional, not
    required, so this returns plain defaults rather than erroring.
    """
    if path is None:
        if not Path(DEFAULT_CONFIG_FILENAME).is_file():
            return WattageConfig()
        path = DEFAULT_CONFIG_FILENAME

    try:
        with open(path, encoding="utf-8") as f:
            raw: Any = yaml.safe_load(f)
    except OSError as exc:
        raise WattageConfigError(f"could not read config file {path!r}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise WattageConfigError(f"invalid YAML in {path!r}: {exc}") from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise WattageConfigError(
            f"{path!r} must be a YAML mapping at the top level, got {type(raw).__name__}"
        )

    try:
        return WattageConfig.model_validate(raw)
    except ValidationError as exc:
        raise WattageConfigError(f"invalid config in {path!r}:\n{exc}") from exc
