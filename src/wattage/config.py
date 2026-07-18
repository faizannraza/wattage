"""wattage.yaml config schema (doc §9.6) — the subset needed by Phase 1's
detectors. nonconvergence/retrieval_thrash/model_mismatch/reasoning_overspend
sections land alongside their detectors in later phases.
"""

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
    exempt_tools: list[str] = Field(
        default_factory=lambda: ["poll_status", "wait", "healthcheck"]
    )


class DetectorsConfig(BaseModel):
    prefix_churn: PrefixChurnConfig = Field(default_factory=PrefixChurnConfig)
    cache_gap: CacheGapConfig = Field(default_factory=CacheGapConfig)
    verbosity: VerbosityConfig = Field(default_factory=VerbosityConfig)
    redundant_tool_calls: RedundantToolCallsConfig = Field(
        default_factory=RedundantToolCallsConfig
    )


class WattageConfig(BaseModel):
    detectors: DetectorsConfig = Field(default_factory=DetectorsConfig)
