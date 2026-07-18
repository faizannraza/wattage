from pathlib import Path

import pytest

from wattage.models import LLMCall, TokenUsage
from wattage.pricing.engine import PricingEngine
from wattage.pricing.registry import PricingRegistry


@pytest.fixture
def engine() -> PricingEngine:
    return PricingEngine(PricingRegistry.load())


def test_prices_known_model_across_all_token_classes(engine: PricingEngine) -> None:
    call = LLMCall(
        span_id="s1",
        provider="anthropic",
        model="claude-sonnet-4-6",
        usage=TokenUsage(input=10_000, output=300, cache_read=40_000, cache_creation=2_000),
    )
    cost = engine.price_call(call)

    assert cost.unpriced is False
    assert cost.input == pytest.approx(10_000 * 3.0e-6)
    assert cost.output == pytest.approx(300 * 15.0e-6)
    assert cost.cache_read == pytest.approx(40_000 * 3.0e-6 * 0.10)
    assert cost.cache_creation == pytest.approx(2_000 * 3.0e-6 * 1.25)
    assert cost.total == pytest.approx(
        cost.input + cost.output + cost.cache_read + cost.cache_creation
    )
    assert cost.pricing_version == "2026-07-18-verified"


def test_unknown_model_warns_and_is_left_unpriced(engine: PricingEngine) -> None:
    call = LLMCall(
        span_id="s2", provider="mystery-provider", model="ghost-model", usage=TokenUsage(input=100)
    )
    with pytest.warns(UserWarning, match="ghost-model"):
        cost = engine.price_call(call)

    assert cost.unpriced is True
    assert cost.total == 0
    assert cost.input == 0


def test_registry_overrides_merge_over_vendored(tmp_path: Path) -> None:
    override_path = tmp_path / "overrides.yaml"
    override_path.write_text(
        "version: 'test-override'\n"
        "providers:\n"
        "  anthropic:\n"
        "    claude-sonnet-4-6:\n"
        "      input: 1.0e-6\n"
        "      output: 2.0e-6\n"
        "      cache_read_mult: 0.5\n"
        "      cache_write_mult: 1.0\n"
        "      min_cacheable_prefix_tokens: 1024\n"
    )
    registry = PricingRegistry.load(overrides_path=str(override_path))
    assert registry.version == "test-override"
    price = registry.get("anthropic", "claude-sonnet-4-6")
    assert price.input == 1.0e-6
    assert price.cache_read_mult == 0.5

    # An untouched model from the vendored snapshot must still resolve.
    haiku_price = registry.get("anthropic", "claude-haiku-4-5")
    assert haiku_price.input == 1.0e-6
