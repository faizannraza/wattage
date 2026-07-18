import pytest

from wattage.convergence.embed import HashEmbedder, NullEmbedder
from wattage.convergence.signals import (
    action_text,
    canonical_action_symbol,
    compute_iteration_signals,
    evidence_gain,
    growth_penalty,
    new_information_text,
    oscillation_score,
    state_delta,
)
from wattage.models import Iteration, LLMCall, TokenUsage, ToolCall


def _tool(name: str, args: dict[str, object], result: str | None = None) -> ToolCall:
    return ToolCall(span_id="s", name=name, args=args, args_hash="h", result=result, start_ns=0)


def _llm(input_tok: int = 100, output_tok: int = 10) -> LLMCall:
    return LLMCall(
        span_id="l",
        provider="anthropic",
        model="claude-sonnet-4-6",
        usage=TokenUsage(input=input_tok, output=output_tok),
        start_ns=0,
    )


def test_new_information_text_concatenates_tool_results() -> None:
    it = Iteration(
        index=0,
        tool_calls=[_tool("a", {}, result="result one"), _tool("b", {}, result="result two")],
    )
    assert new_information_text(it) == "result one\nresult two"


def test_new_information_text_empty_when_no_results() -> None:
    it = Iteration(index=0, tool_calls=[_tool("a", {}, result=None)])
    assert new_information_text(it) == ""


def test_canonical_action_symbol_is_chat_only_without_tool_calls() -> None:
    it = Iteration(index=0, llm_calls=[_llm()])
    assert canonical_action_symbol(it) == "chat_only"


def test_canonical_action_symbol_ignores_args() -> None:
    it_a = Iteration(index=0, tool_calls=[_tool("search", {"attempt": 1})])
    it_b = Iteration(index=0, tool_calls=[_tool("search", {"attempt": 999})])
    assert canonical_action_symbol(it_a) == canonical_action_symbol(it_b) == "search"


def test_canonical_action_symbol_sorts_multiple_tools() -> None:
    it = Iteration(index=0, tool_calls=[_tool("zzz", {}), _tool("aaa", {})])
    assert canonical_action_symbol(it) == "aaa,zzz"


def test_action_text_uses_tool_calls_when_present() -> None:
    it = Iteration(index=0, tool_calls=[_tool("search", {"q": "x"})])
    assert "search" in action_text(it)


def test_evidence_gain_delegates_to_embedder_novelty() -> None:
    embedder = HashEmbedder()
    assert evidence_gain("new content", [], embedder) == embedder.novelty("new content", [])


def test_state_delta_first_iteration_is_always_one() -> None:
    embedder = NullEmbedder()
    assert state_delta("anything", None, embedder) == 1.0


def test_state_delta_uses_only_the_immediately_prior_action() -> None:
    embedder = HashEmbedder()
    assert state_delta("same action", "same action", embedder) == pytest.approx(0.0, abs=1e-9)


def test_growth_penalty_zero_when_no_tokens_added() -> None:
    assert growth_penalty(added_tokens=0, new_evidence_tokens=100) == 0.0


def test_growth_penalty_high_when_much_growth_little_evidence() -> None:
    high = growth_penalty(added_tokens=10_000, new_evidence_tokens=10)
    low = growth_penalty(added_tokens=100, new_evidence_tokens=100)
    assert high > low
    assert 0.0 <= high < 1.0


class TestOscillationScore:
    def test_clean_period_two_cycle_scores_high(self) -> None:
        assert oscillation_score(["A", "B", "A", "B", "A", "B"]) == 1.0

    def test_clean_period_three_cycle_scores_high(self) -> None:
        assert oscillation_score(["A", "B", "C", "A", "B", "C"]) == 1.0

    def test_uniform_repetition_is_not_oscillation(self) -> None:
        """Period-1 repetition is thrashing's signature, not oscillation's."""
        assert oscillation_score(["A", "A", "A", "A", "A", "A"]) == 0.0

    def test_non_periodic_sequence_scores_zero(self) -> None:
        assert oscillation_score(["A", "B", "X", "A", "B", "Y"]) == 0.0

    def test_too_short_for_two_full_cycles_scores_zero(self) -> None:
        assert oscillation_score(["A", "B", "A"]) == 0.0

    def test_robust_to_arg_noise_via_canonical_symbols(self) -> None:
        """The whole point: incrementing IDs must not defeat cycle detection
        once symbols are canonicalized to tool names only."""
        symbols = [
            canonical_action_symbol(Iteration(index=i, tool_calls=[_tool(name, {"attempt": i})]))
            for i, name in enumerate(["search", "verify", "search", "verify", "search", "verify"])
        ]
        assert oscillation_score(symbols) == 1.0


def test_compute_iteration_signals_first_iteration_has_no_growth_penalty() -> None:
    iterations = [Iteration(index=0, llm_calls=[_llm(500, 50)], tool_calls=[_tool("a", {}, "x")])]
    signals = compute_iteration_signals(iterations, HashEmbedder())
    assert signals[0].growth_penalty == 0.0
    assert signals[0].state_delta == 1.0


def test_compute_iteration_signals_returns_one_entry_per_iteration() -> None:
    iterations = [
        Iteration(index=0, llm_calls=[_llm()], tool_calls=[_tool("a", {}, "x")]),
        Iteration(index=1, llm_calls=[_llm()], tool_calls=[_tool("b", {}, "y")]),
        Iteration(index=2, llm_calls=[_llm()]),
    ]
    signals = compute_iteration_signals(iterations, HashEmbedder())
    assert len(signals) == 3
