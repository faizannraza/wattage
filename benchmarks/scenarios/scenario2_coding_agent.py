"""Scenario 2: autonomous coding agent, large multi-file refactor.
See GROUND_TRUTH.md for the full spec. Single task (no invoke_agent spans
at all -- tests the catch-all-task path), one 22-iteration loop.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from span_builder import chat_span, tool_span, wrap_otlp_json  # noqa: E402

TRACE = "trace-coding-001"
spans = []
t = 0
MODEL = ("anthropic", "claude-sonnet-4-6")


def adv(ns):
    global t
    t += ns


def add_iter(
    idx,
    input_tok,
    output_tok,
    tool_name=None,
    args=None,
    result=None,
    reasoning_tok=0,
    max_tokens=None,
):
    spans.append(
        chat_span(
            f"c{idx}",
            None,
            TRACE,
            t,
            500_000_000,
            MODEL[0],
            MODEL[1],
            input_tok,
            output_tok,
            reasoning_tokens=reasoning_tok,
            max_tokens=max_tokens,
        )
    )
    adv(500_000_000)
    if tool_name:
        spans.append(tool_span(f"t{idx}", None, TRACE, t, 300_000_000, tool_name, args, result))
        adv(300_000_000)
    adv(100_000_000)


# it0-4: genuine exploration, includes one exact-repeat read_file(config.py) -> redundant_tool_calls
add_iter(
    0,
    2000,
    120,
    "list_files",
    {"dir": "/repo/src"},
    "Found 15 files: main.py, utils.py, config.py, auth.py, db.py, ...",
)
add_iter(
    1,
    2200,
    150,
    "read_file",
    {"path": "/repo/src/config.py"},
    "DATABASE_URL = os.environ['DATABASE_URL']\nDEBUG = False\nMAX_RETRIES = 3",
)
add_iter(
    2,
    2450,
    180,
    "read_file",
    {"path": "/repo/src/auth.py"},
    "def authenticate(token):\n    return jwt.decode(token, SECRET_KEY, algorithms=['HS256'])",
)
add_iter(
    3,
    2700,
    140,
    "read_file",
    {"path": "/repo/src/config.py"},  # exact repeat of it1's args
    "DATABASE_URL = os.environ['DATABASE_URL']\nDEBUG = False\nMAX_RETRIES = 3",
)
add_iter(
    4,
    2950,
    130,
    "grep",
    {"pattern": "TODO", "dir": "/repo/src"},
    "3 matches: auth.py:42, db.py:88, main.py:12",
)

# it5: verbosity bait -- huge uncapped output summarizing a file
add_iter(
    5,
    3200,
    1600,
    "read_file",
    {"path": "/repo/README.md"},
    "# Project overview\nA REST API service with JWT auth and a Postgres backend.",
)

# it6: reasoning_overspend bait -- heavy reasoning, small output.
# output_tok (755) is the raw wire value -- inclusive of the 700
# reasoning tokens, matching real provider behavior -- so the visible
# output normalize.py derives is 755 - 700 = 55 tokens.
add_iter(
    6,
    5000,
    755,
    "analyze_stacktrace",
    {"trace_id": "exc-991"},
    "NullPointerException at db.py line 88, triggered by missing null check",
    reasoning_tok=700,
)

# it7-21: STALLED pattern at real scale -- 15 iterations, same tool, growing input,
# near-identical boilerplate result, never recovers.
STALL_RESULT = "FAILED: 2 tests still failing"
input_base = 5300
for k in range(15):
    idx = 7 + k
    add_iter(idx, input_base + k * 400, 30, "run_tests", {"attempt": k}, STALL_RESULT)

trace = wrap_otlp_json(spans, service_name="coding-agent")
out_path = Path(__file__).parent / "scenario2.json"
with open(out_path, "w") as f:
    json.dump(trace, f, indent=2)

print(f"wrote {out_path}: {len(spans)} spans, {7 + 15} llm iterations total (22)")
