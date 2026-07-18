"""Quality gating (doc §6.3).

Real quality_factor computation from a user-supplied --quality quality.json
(per-task/step eval scores) lands in Phase 3 alongside model_mismatch and
reasoning_overspend, the two detectors whose findings actually need it. For
now this always reports the honest "unmeasured" default — quality_factor=1,
quality_measured=False — rather than pretending to gate on quality it
hasn't actually looked at.
"""

from __future__ import annotations

from typing import Any


def compute_quality_factor(quality_map: dict[str, Any] | None) -> tuple[float, bool]:
    # `quality_map` is accepted now so call sites don't change in Phase 3,
    # but it's intentionally ignored until then.
    return 1.0, False
