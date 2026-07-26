"""Shared display formatting for renderers.

A genuinely nonzero finding must never visually read as "$0.0000" — that
looks like a rounding bug (or "no real waste") even when the underlying
number is correct and honestly computed; sub-cent findings from small
token counts are common (redundant_tool_calls, retrieval_thrash) and would
otherwise all collapse to the same misleading zero-looking figure.
"""

from __future__ import annotations


def format_dollars(amount: float) -> str:
    if amount == 0 or round(amount, 4) != 0:
        return f"${amount:.4f}"
    for decimals in (6, 8, 10):
        if round(amount, decimals) != 0:
            return f"${amount:.{decimals}f}"
    return f"${amount:.10f}"
