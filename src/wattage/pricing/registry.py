"""Pricing registry (doc §7.5 / §9.4): loads the vendored snapshot plus optional
user overrides, and resolves a (provider, model) pair to its rate card.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ModelPrice:
    input: float
    output: float
    cache_read_mult: float
    cache_write_mult: float
    min_cacheable_prefix_tokens: int


class UnknownModelError(LookupError):
    """No registry entry for (provider, model); the caller must warn, not guess."""


class PricingRegistry:
    def __init__(self, providers: dict[str, dict[str, Any]], version: str) -> None:
        self._providers = providers
        self.version = version

    @classmethod
    def load(
        cls,
        path: str | Path | None = None,
        overrides_path: str | Path | None = None,
    ) -> PricingRegistry:
        raw = cls._load_yaml(path) if path is not None else cls._load_vendored()
        providers: dict[str, dict[str, Any]] = raw.get("providers", {})
        version: str = raw.get("version", "unknown")

        if overrides_path is not None:
            override_raw = cls._load_yaml(overrides_path)
            for provider, models in override_raw.get("providers", {}).items():
                providers.setdefault(provider, {}).update(models)
            version = override_raw.get("version", version)

        return cls(providers, version)

    @staticmethod
    def _load_vendored() -> dict[str, Any]:
        vendored = resources.files("wattage.pricing.data").joinpath("pricing.yaml")
        loaded = yaml.safe_load(vendored.read_text(encoding="utf-8"))
        return dict(loaded) if loaded else {}

    @staticmethod
    def _load_yaml(path: str | Path) -> dict[str, Any]:
        with open(path, encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        return dict(loaded) if loaded else {}

    def get(self, provider: str, model: str) -> ModelPrice:
        provider_models = self._providers.get(provider)
        if provider_models is None or model not in provider_models:
            raise UnknownModelError(f"No pricing entry for {provider}/{model}")
        m = provider_models[model]
        return ModelPrice(
            input=m["input"],
            output=m["output"],
            cache_read_mult=m.get("cache_read_mult", 1.0),
            cache_write_mult=m.get("cache_write_mult", 1.0),
            min_cacheable_prefix_tokens=m.get("min_cacheable_prefix_tokens", 0),
        )
