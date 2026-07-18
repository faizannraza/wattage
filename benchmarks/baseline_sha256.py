"""SHA-256 exact-match baseline (doc plan 2.8): a small reference
implementation of the "shallow loop-guard" pattern doc §5.1 critiques
(OpenFang's loop_guard.rs, Genkit's smartMaxTurns, Strands debounce hooks) —
exact hash of tool name + args, sliding window, nothing fuzzy, no semantic
signal at all. This exists specifically to reproduce those blind spots for a
real (not asserted) comparison against wattage's convergence classifier.

Binary only: "flagged" (an exact-duplicate tool call was seen within the
window) vs "not flagged" — a hash-of-exact-args detector has no way to
express thrashing vs oscillating vs stalled as distinct concepts, only "did
I see the exact same call before".
"""

from __future__ import annotations

import hashlib
import json
from collections import deque

from wattage.models import Loop, ToolCall


def _exact_key(call: ToolCall) -> str:
    canonical = json.dumps(call.args, sort_keys=True, default=str)
    return hashlib.sha256(f"{call.name}:{canonical}".encode()).hexdigest()


def baseline_flags_loop(loop: Loop, window: int = 5) -> bool:
    """True if an exact-match duplicate tool call was found anywhere within
    the trailing sliding window across the loop's iterations."""
    calls: list[ToolCall] = [tc for it in loop.iterations for tc in it.tool_calls]
    seen: deque[str] = deque(maxlen=window)
    for call in calls:
        key = _exact_key(call)
        if key in seen:
            return True
        seen.append(key)
    return False
