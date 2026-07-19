"""Per-iteration progress signals (doc §5.2).

The doc's five/six signals assume richer structure than a generic OTel trace
actually carries (no explicit "plan"/"goal" field, no tokenizer). Each
signal below is implemented against what's genuinely measurable, with the
approximation spelled out rather than glossed over:

- Evidence gain (E): novelty of this iteration's tool/retrieval *results*
  against everything seen so far (cumulative). Answers "did we learn
  something new".
- State delta (S): novelty of this iteration's *action* (which tool, what
  args, or the final answer text) against only the immediately prior
  iteration's action — local, not cumulative, which is what keeps it a
  distinct signal from E rather than a restatement of it. Answers "did the
  agent's behavior actually change step to step".
- Oscillation (O): periodicity (period >= 2 only — a single repeated action
  is thrashing's signature, not oscillation's) in the tool-name-based action
  symbol sequence, requiring at least two full cycles before registering
  any score. Deliberately ignores args so it stays robust to incrementing
  counters/timestamps that would defeat exact matching.
- Growth-vs-information (G): ratio of new context tokens paid for this
  iteration to the size of genuinely new tool/retrieval result content that
  arrived — independent of E, so a loop can score low E (repetitive
  results) yet still be assessed on whether that repetition was cheap or
  expensive.
- Goal proximity (P): only meaningful with an explicit goal signal, which
  nothing currently populates (Loop.goal_signal defaults to None) — defaults
  to a neutral 0.5 baseline (contributes evenly to every iteration, so it
  doesn't discriminate progress classification) rather than a fabricated
  confident value.
"""

from __future__ import annotations

from dataclasses import dataclass

from wattage.convergence.embed import Embedder
from wattage.models import Iteration

_CHARS_PER_TOKEN = 4


@dataclass
class IterationSignals:
    evidence_gain: float
    state_delta: float
    oscillation: float
    growth_penalty: float
    goal_proximity: float


def new_information_text(iteration: Iteration) -> str:
    """What came *back* this iteration: tool/retrieval results."""
    parts = [tc.result for tc in iteration.tool_calls if tc.result]
    for retrieval in iteration.retrievals:
        for chunk in retrieval.chunks:
            text = chunk.get("text") if isinstance(chunk, dict) else None
            if text:
                parts.append(str(text))
    return "\n".join(parts)


def action_text(iteration: Iteration) -> str:
    """What the agent *decided* this iteration: which tool(s) with what args,
    or its final-answer text when there's no tool call at all."""
    if iteration.tool_calls:
        return "\n".join(f"{tc.name}({tc.args})" for tc in iteration.tool_calls)
    if iteration.llm_calls and iteration.llm_calls[-1].messages:
        return str(iteration.llm_calls[-1].messages)
    return ""


def canonical_action_symbol(
    iteration: Iteration, exempt_tools: frozenset[str] = frozenset()
) -> str:
    """Tool-name-only symbol for oscillation's cycle detection — deliberately
    ignores args so incrementing counters/timestamps don't defeat it.

    When every tool call in the iteration is on the exempt list (legitimate
    repetition, e.g. polling), the symbol is made unique per iteration
    instead — it can never equal another iteration's symbol, so exempt
    activity can never itself register as a cycle."""
    names = [tc.name for tc in iteration.tool_calls]
    if names and all(n in exempt_tools for n in names):
        return f"exempt:{iteration.index}"
    if names:
        return ",".join(sorted(names))
    return "chat_only"


def evidence_gain(new_info: str, prior_infos: list[str], embedder: Embedder) -> float:
    return embedder.novelty(new_info, prior_infos)


def state_delta(curr_action: str, prior_action: str | None, embedder: Embedder) -> float:
    if prior_action is None:
        return 1.0  # nothing to compare against yet; the first iteration always "changes state"
    return embedder.novelty(curr_action, [prior_action])


def oscillation_score(symbols: list[str], window: int = 6, max_period: int = 4) -> float:
    trailing = symbols[-window:]
    n = len(trailing)
    best = 0.0
    for period in range(2, max_period + 1):
        max_cycles = n // period
        if max_cycles < 2:
            continue
        base = trailing[n - period :]
        if len(set(base)) < 2:
            continue  # a uniform "cycle" is really period-1 repetition (thrashing's territory)
        repeats = 1
        for c in range(2, max_cycles + 1):
            chunk = trailing[n - c * period : n - (c - 1) * period]
            if chunk == base:
                repeats += 1
            else:
                break
        if repeats >= 2:
            score = (repeats - 1) / (max_cycles - 1) if max_cycles > 1 else 1.0
            best = max(best, min(1.0, score))
    return best


def growth_penalty(added_tokens: int, new_evidence_tokens: int) -> float:
    if added_tokens <= 0:
        return 0.0
    ratio = added_tokens / max(new_evidence_tokens, 1)
    return ratio / (ratio + 1.0)  # squash to [0, 1); large ratio -> approaches 1


def goal_proximity(action_or_info: str, goal_signal: str | None, embedder: Embedder) -> float:
    if goal_signal is None or not action_or_info:
        return 0.5
    return embedder.similarity(action_or_info, goal_signal)


def _iteration_input_tokens(iteration: Iteration) -> int:
    return sum(c.usage.input for c in iteration.llm_calls)


def _iteration_total_tokens(iteration: Iteration) -> int:
    return sum(c.usage.input + c.usage.output for c in iteration.llm_calls)


def compute_iteration_signals(
    iterations: list[Iteration],
    embedder: Embedder,
    goal_signal: str | None = None,
    oscillation_window: int = 6,
    max_period: int = 4,
    exempt_tools: frozenset[str] = frozenset(),
) -> list[IterationSignals]:
    prior_infos: list[str] = []
    action_symbols: list[str] = []
    prior_action: str | None = None
    prior_total_tokens: int | None = None
    results: list[IterationSignals] = []

    for iteration in iterations:
        info = new_information_text(iteration)
        action = action_text(iteration)
        symbol = canonical_action_symbol(iteration, exempt_tools)
        action_symbols.append(symbol)

        e = evidence_gain(info, prior_infos, embedder)
        s = state_delta(action, prior_action, embedder)
        o = oscillation_score(action_symbols, window=oscillation_window, max_period=max_period)

        if prior_total_tokens is None:
            g = 0.0  # first iteration establishes the baseline context; no "growth" to penalize
        else:
            added = max(0, _iteration_input_tokens(iteration) - prior_total_tokens)
            new_evidence_tokens = len(info) // _CHARS_PER_TOKEN
            g = growth_penalty(added, new_evidence_tokens)

        p = goal_proximity(action or info, goal_signal, embedder)

        results.append(
            IterationSignals(
                evidence_gain=e, state_delta=s, oscillation=o, growth_penalty=g, goal_proximity=p
            )
        )

        if info:
            prior_infos.append(info)
        prior_action = action
        prior_total_tokens = _iteration_total_tokens(iteration)

    return results
