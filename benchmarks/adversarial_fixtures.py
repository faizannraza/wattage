"""Labeled adversarial fixture set (doc plan 2.7): hand-crafted synthetic
loops with known ground-truth convergence classification, used by
benchmarks/harness.py to compare Wattage's classifier against the SHA-256
exact-match baseline.

Every label was verified empirically against the actual classifier before
being committed here (see benchmarks/verify_fixtures.py) — this file is the
credibility backbone for every downstream F1 claim, so a label is only
correct if a human reviewing the fixture's construction would agree with it
on inspection, not just because the code currently agrees with itself.

All fixtures use `reached_success=False` uniformly, even the productive
ones — this deliberately exercises the real classifier logic (does it
correctly recognize genuine progress) rather than the separate
reached_success shortcut, which already has dedicated coverage in
tests/test_detector_convergence.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from wattage.models import Iteration, LLMCall, Loop, TokenUsage, ToolCall


@dataclass
class LabeledLoop:
    name: str
    loop: Loop
    label: str  # "productive" | "thrashing" | "oscillating" | "stalled"
    note: str


def _llm(span_id: str, input_tok: int, output_tok: int = 50) -> LLMCall:
    return LLMCall(
        span_id=span_id,
        provider="anthropic",
        model="claude-sonnet-4-6",
        usage=TokenUsage(input=input_tok, output=output_tok),
        start_ns=0,
    )


def _tool(span_id: str, name: str, args: dict[str, object], result: str) -> ToolCall:
    return ToolCall(
        span_id=span_id, name=name, args=args, args_hash="x", result=result, start_ns=0
    )


def _iter(
    index: int,
    input_tok: int,
    tool_name: str | None = None,
    args: dict[str, object] | None = None,
    result: str | None = None,
    output_tok: int = 50,
) -> Iteration:
    tool_calls = [_tool(f"t{index}", tool_name, args or {}, result or "")] if tool_name else []
    return Iteration(
        index=index,
        llm_calls=[_llm(f"l{index}", input_tok, output_tok)],
        tool_calls=tool_calls,
    )


def _loop(name: str, iterations: list[Iteration]) -> Loop:
    return Loop(loop_id=name, iterations=iterations, reached_success=False)


FIXTURES: list[LabeledLoop] = []

# ============================== productive ==============================

FIXTURES.append(
    LabeledLoop(
        name="linear_research",
        loop=_loop(
            "linear_research",
            [
                _iter(
                    0, 500, "search_docs", {"q": "refund policy"},
                    "Refund policy: full refund within 30 days if the item is unused.",
                ),
                _iter(
                    1, 700, "search_docs", {"q": "shipping policy"},
                    "Shipping policy: orders ship within 2 business days via standard carrier.",
                ),
                _iter(2, 900),  # final answer, chat only, no further tool call
            ],
        ),
        label="productive",
        note="Each turn retrieves genuinely different, useful content; ends in a final answer.",
    )
)

FIXTURES.append(
    LabeledLoop(
        name="multi_tool_pipeline",
        loop=_loop(
            "multi_tool_pipeline",
            [
                _iter(
                    0, 400, "list_files", {"dir": "/repo/src"},
                    "Found 12 files: main.py, utils.py, config.py, ...",
                ),
                _iter(
                    1, 600, "read_file", {"path": "/repo/src/config.py"},
                    "DATABASE_URL = os.environ['DATABASE_URL']\nDEBUG = False",
                ),
                _iter(
                    2, 800, "grep", {"pattern": "DATABASE_URL", "dir": "/repo"},
                    "src/config.py:1\nsrc/db.py:15\ntests/test_db.py:8",
                ),
                _iter(3, 950),  # final answer
            ],
        ),
        label="productive",
        note=(
            "Different tool each step (list -> read -> grep -> answer), each producing "
            "genuinely new information. Different-action-each-time must not be confused "
            "with the stalled/thrashing patterns below."
        ),
    )
)

FIXTURES.append(
    LabeledLoop(
        name="iterative_narrowing",
        loop=_loop(
            "iterative_narrowing",
            [
                _iter(
                    0, 500, "search_web", {"q": "python asyncio deadlock"},
                    "Common causes: awaiting a lock already held by the same task, "
                    "blocking calls inside a coroutine.",
                ),
                _iter(
                    1, 750, "search_web", {"q": "asyncio deadlock same task double lock"},
                    "Reentrant lock acquisition in asyncio.Lock is not supported; use "
                    "asyncio.Semaphore or restructure to avoid nested acquisition.",
                ),
                _iter(2, 1000),  # final answer
            ],
        ),
        label="productive",
        note=(
            "Same tool reused, but each query narrows in and returns materially "
            "different content."
        ),
    )
)

# ============================== thrashing ==============================

FIXTURES.append(
    LabeledLoop(
        name="retry_same_failure",
        loop=_loop(
            "retry_same_failure",
            [
                _iter(i, 500, "run_tests", {"attempt": i}, "FAILED: assertion error at line 42")
                for i in range(5)
            ],
        ),
        label="thrashing",
        note=(
            "Baseline blind spot: incrementing 'attempt' defeats exact-hash matching, but "
            "the failure is identical every time and context doesn't grow (flat cost)."
        ),
    )
)

FIXTURES.append(
    LabeledLoop(
        name="identical_repeat_control",
        loop=_loop(
            "identical_repeat_control",
            [
                _iter(i, 500, "build_project", {"target": "release"}, "BUILD FAILED: linker error")
                for i in range(5)
            ],
        ),
        label="thrashing",
        note=(
            "A control case with byte-identical args every time — the baseline *should* "
            "catch this one too (used to confirm wattage isn't worse on the easy cases)."
        ),
    )
)

FIXTURES.append(
    LabeledLoop(
        name="rephrased_retry",
        loop=_loop(
            "rephrased_retry",
            [
                _iter(
                    i, 500 + i * 50, "web_search", {"query": query}, "No relevant results found."
                )
                for i, query in enumerate(
                    [
                        "how to fix connection refused error",
                        "fix connection refused error please",
                        "resolve connection refused issue",
                        "connection refused error solution",
                    ]
                )
            ],
        ),
        label="thrashing",
        note=(
            "Baseline blind spot via wording, not numbers: each query is a fully different "
            "string (never hash-equal), but semantically the same failing search repeated, "
            "with identical unhelpful results."
        ),
    )
)

# ============================== oscillating ==============================

FIXTURES.append(
    LabeledLoop(
        name="check_retry_cycle",
        loop=_loop(
            "check_retry_cycle",
            [
                _iter(
                    i,
                    500 + i * 50,
                    "check_status" if i % 2 == 0 else "retry_action",
                    {"id": i},
                    "status: pending, no change" if i % 2 == 0 else "retried, no effect",
                )
                for i in range(6)
            ],
        ),
        label="oscillating",
        note=(
            "Clean period-2 cycle (check_status <-> retry_action) with incrementing 'id' "
            "(fuzzy — defeats exact match) and near-identical unhelpful results each cycle."
        ),
    )
)

FIXTURES.append(
    LabeledLoop(
        name="three_way_debug_cycle",
        loop=_loop(
            "three_way_debug_cycle",
            [
                _iter(i, 500 + i * 30, name, {"round": i}, result)
                for i, (name, result) in enumerate(
                    [
                        ("try_fix", "applied patch v1"),
                        ("run_tests", "FAILED: 3 tests still failing"),
                        ("analyze_failure", "same 3 tests failing as before"),
                        ("try_fix", "applied patch v2"),
                        ("run_tests", "FAILED: 3 tests still failing"),
                        ("analyze_failure", "same 3 tests failing as before"),
                    ]
                )
            ],
        ),
        label="oscillating",
        note="Period-3 cycle (try_fix -> run_tests -> analyze_failure) x2, going nowhere.",
    )
)

# ============================== stalled ==============================

FIXTURES.append(
    LabeledLoop(
        name="growing_context_no_evidence",
        loop=_loop(
            "growing_context_no_evidence",
            [
                _iter(
                    i,
                    2000 + (i + 1) * 8000,
                    "run_tests",
                    {"attempt": i},
                    "FAILED: same error",
                    output_tok=30,
                )
                for i in range(5)
            ],
        ),
        label="stalled",
        note=(
            "The doc's signature blind spot: action stays near-static (same tool, fuzzy "
            "args -> zero exact duplicates) while context balloons every turn and results "
            "stay boilerplate. Distinguished from 'retry_same_failure' by the growing cost."
        ),
    )
)

FIXTURES.append(
    LabeledLoop(
        name="silent_diagnostic_stall",
        loop=_loop(
            "silent_diagnostic_stall",
            [
                _iter(
                    i,
                    3000 + (i + 1) * 6000,
                    "check_disk_space",
                    {"probe": i},
                    "no anomalies detected",
                    output_tok=25,
                )
                for i in range(4)
            ],
        ),
        label="stalled",
        note=(
            "Same diagnostic tool, fuzzy probe id, uninformative result, steadily "
            "growing context."
        ),
    )
)
