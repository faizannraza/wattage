"""Cost Engine (doc §9.4): prices an LLMCall across its token classes.

Unknown models warn and leave the call unpriced — never a fabricated number.
"""

from __future__ import annotations

import warnings

from wattage.models import Cost, LLMCall
from wattage.pricing.registry import PricingRegistry, UnknownModelError


class PricingEngine:
    def __init__(self, registry: PricingRegistry) -> None:
        self.registry = registry

    def price_call(self, call: LLMCall) -> Cost:
        try:
            price = self.registry.get(call.provider, call.model)
        except UnknownModelError:
            warnings.warn(
                f"No pricing entry for {call.provider}/{call.model}; "
                "leaving this call unpriced rather than guessing a rate.",
                stacklevel=2,
            )
            return Cost(pricing_version=self.registry.version, unpriced=True)

        usage = call.usage
        input_cost = usage.input * price.input
        output_cost = usage.output * price.output
        cache_read_cost = usage.cache_read * price.input * price.cache_read_mult
        cache_creation_cost = usage.cache_creation * price.input * price.cache_write_mult
        reasoning_cost = usage.reasoning * price.output
        total = input_cost + output_cost + cache_read_cost + cache_creation_cost + reasoning_cost

        return Cost(
            input=input_cost,
            output=output_cost,
            cache_read=cache_read_cost,
            cache_creation=cache_creation_cost,
            reasoning=reasoning_cost,
            total=total,
            pricing_version=self.registry.version,
        )
