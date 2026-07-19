"""wattage.yaml config schema (doc §9.6)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PrefixChurnConfig(BaseModel):
    enabled: bool = True
    # A finding's severity is "high" once its share of the task's total cost
    # crosses this ratio (doc §4.1: "severity from resent_dollars/session_dollars").
    high_severity_ratio: float = 0.30


class CacheGapConfig(BaseModel):
    enabled: bool = True


class VerbosityConfig(BaseModel):
    enabled: bool = True
    # Calls with no max_tokens cap that generate more than this many output
    # tokens are flagged. A single global ceiling, not doc §9.6's per-task-type
    # bands (extract/classify/draft) — those need task-type classification,
    # which doesn't exist yet; revisit once it does.
    expected_output_ceiling: int = 1000
    high_severity_multiplier: float = 3.0


class RedundantToolCallsConfig(BaseModel):
    enabled: bool = True
    window: int = 5
    fuzzy: bool = True
    exempt_tools: list[str] = Field(default_factory=lambda: ["poll_status", "wait", "healthcheck"])


class ConvergenceWeightsConfig(BaseModel):
    """Field names match doc §5.3's notation (E/S/P/O/G) exactly, on purpose."""

    E: float = 0.40
    S: float = 0.20
    P: float = 0.20
    O: float = 0.15  # noqa: E741 (ambiguous-with-zero; matches doc notation deliberately)
    G: float = 0.05


class NonConvergenceConfig(BaseModel):
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


class RetrievalThrashConfig(BaseModel):
    enabled: bool = True
    relevance_threshold: float = 0.35
    max_iterations_soft: int = 4


class ModelMismatchConfig(BaseModel):
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


class ReasoningOverspendConfig(BaseModel):
    enabled: bool = True
    expected_reasoning_ceiling: int = 500
    simple_output_ceiling: int = 150


class DetectorsConfig(BaseModel):
    prefix_churn: PrefixChurnConfig = Field(default_factory=PrefixChurnConfig)
    cache_gap: CacheGapConfig = Field(default_factory=CacheGapConfig)
    verbosity: VerbosityConfig = Field(default_factory=VerbosityConfig)
    redundant_tool_calls: RedundantToolCallsConfig = Field(default_factory=RedundantToolCallsConfig)
    nonconvergence: NonConvergenceConfig = Field(default_factory=NonConvergenceConfig)
    retrieval_thrash: RetrievalThrashConfig = Field(default_factory=RetrievalThrashConfig)
    model_mismatch: ModelMismatchConfig = Field(default_factory=ModelMismatchConfig)
    reasoning_overspend: ReasoningOverspendConfig = Field(default_factory=ReasoningOverspendConfig)


class QualityConfig(BaseModel):
    target: float = 0.90


class CIFailOnConfig(BaseModel):
    score_below: int | None = 80
    cost_delta_pct_above: float | None = 5.0
    any_critical: bool = True


class CIConfig(BaseModel):
    baseline_path: str = ".wattage/baseline.json"
    rolling_window_days: int = 7
    fail_on: CIFailOnConfig = Field(default_factory=CIFailOnConfig)
    pr_comment: bool = True
    badge_out: str | None = None
    sarif_out: str | None = None


class WattageConfig(BaseModel):
    detectors: DetectorsConfig = Field(default_factory=DetectorsConfig)
    quality: QualityConfig = Field(default_factory=QualityConfig)
    ci: CIConfig = Field(default_factory=CIConfig)
