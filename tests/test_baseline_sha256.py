from benchmarks.baseline_sha256 import baseline_flags_loop
from wattage.models import Iteration, Loop, ToolCall


def _tool(span_id: str, name: str, args: dict[str, object]) -> ToolCall:
    return ToolCall(span_id=span_id, name=name, args=args, args_hash="x", start_ns=0)


def test_flags_byte_identical_repeated_call() -> None:
    iterations = [
        Iteration(index=i, tool_calls=[_tool(f"t{i}", "run_tests", {"target": "release"})])
        for i in range(3)
    ]
    loop = Loop(loop_id="l", iterations=iterations, reached_success=False)
    assert baseline_flags_loop(loop) is True


def test_misses_fuzzy_incrementing_args() -> None:
    """The exact blind spot doc §5.1 calls out."""
    iterations = [
        Iteration(index=i, tool_calls=[_tool(f"t{i}", "run_tests", {"attempt": i})])
        for i in range(5)
    ]
    loop = Loop(loop_id="l", iterations=iterations, reached_success=False)
    assert baseline_flags_loop(loop) is False


def test_does_not_flag_genuinely_distinct_calls() -> None:
    iterations = [
        Iteration(index=0, tool_calls=[_tool("t0", "search", {"q": "a"})]),
        Iteration(index=1, tool_calls=[_tool("t1", "search", {"q": "b"})]),
    ]
    loop = Loop(loop_id="l", iterations=iterations, reached_success=False)
    assert baseline_flags_loop(loop) is False


def test_respects_window_size() -> None:
    iterations = [
        Iteration(index=0, tool_calls=[_tool("t0", "search", {"q": "a"})]),
        Iteration(index=1, tool_calls=[_tool("t1", "filler", {"i": 1})]),
        Iteration(index=2, tool_calls=[_tool("t2", "filler", {"i": 2})]),
        Iteration(index=3, tool_calls=[_tool("t3", "search", {"q": "a"})]),
    ]
    loop = Loop(loop_id="l", iterations=iterations, reached_success=False)
    assert baseline_flags_loop(loop, window=2) is False
    assert baseline_flags_loop(loop, window=5) is True


def test_empty_loop_not_flagged() -> None:
    loop = Loop(loop_id="l", iterations=[], reached_success=False)
    assert baseline_flags_loop(loop) is False
