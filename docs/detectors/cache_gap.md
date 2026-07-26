# cache_gap

**Detects:** caching that's actually turned on but isn't paying for itself — writes without matching reads.

This is distinct from `prefix_churn`, which fires when caching was **never attempted at all**. `cache_gap` only fires once there's evidence caching was configured (`cache_creation` tokens > 0 somewhere in the task) — it's about a misconfiguration, not an absent feature.

## How it works

Cache writes cost a premium over plain input tokens (typically 1.25×–2× depending on provider and TTL), on the assumption that a future cache *read* — billed at roughly 10% of the input rate — will redeem that premium many times over. If a task's total cache reads never catch up to its total cache writes, the unredeemed fraction of every write was pure overhead: a real, quantifiable dollar cost with zero benefit.

The exact premium is computed per model from the vendored pricing registry's `cache_write_mult`, so this scales correctly across providers rather than assuming a single fixed number.

**This detector targets the premium specifically, not the raw cache-write token count.** A provider with no cache-write premium at all (`cache_write_mult == 1.0` in the pricing registry — OpenAI's model today, per its own pricing page) costs exactly the same whether those tokens are cached or sent as plain input, so there is genuinely nothing to redeem and nothing to flag: `cache_gap` will correctly stay silent even on a fully-unread cache write in that case. This is by design, not a missed detection — if you're on a provider like this and expected a finding here, that's why there isn't one.

## Known limitation

The doc's fuller definition of this pattern also includes "a cacheable prefix that falls below the provider's minimum cacheable size." That specific root cause is **not** distinguishable from "caching never enabled" using token counts alone — both produce `cache_creation == cache_read == 0`. Telling them apart needs the request's `cache_control` attribute, which isn't part of the OTel GenAI usage attributes Wattage reads today. Rather than guess, this detector only fires on the write-without-read signature it can actually measure.

## Fix

Move volatile fields (timestamps, request IDs) after the cache breakpoint, raise the cache TTL if writes are happening more often than the content actually changes, or drop `cache_control` entirely if this content genuinely won't be re-read.

## Quality risk: none

Like `prefix_churn`, this is purely a caching-configuration fix — it can't change what the model sees.
