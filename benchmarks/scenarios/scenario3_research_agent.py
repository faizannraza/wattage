"""Scenario 3: RAG research agent, deep nested sub-agents.
See GROUND_TRUTH.md. Structure: orphan pre-processing (no agent at all) ->
orchestrator -> research-lead -> {research-sub-agent-A, research-sub-agent-B,
summarizer} (3 levels deep, 3 siblings under a non-root parent).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from span_builder import agent_span, chat_span, tool_span, wrap_otlp_json  # noqa: E402

TRACE = "trace-research-001"
spans = []
t = 0


def adv(ns):
    global t
    t += ns


# ---- Orphan pre-processing: no agent span at all, own catch-all task ----
spans.append(
    chat_span(
        "orphan-c0",
        None,
        TRACE,
        t,
        400_000_000,
        "anthropic",
        "claude-sonnet-4-6",
        800,
        100,
        cache_creation=500,
    )
)
adv(500_000_000)
spans.append(
    chat_span(
        "orphan-c1",
        None,
        TRACE,
        t,
        400_000_000,
        "anthropic",
        "claude-sonnet-4-6",
        850,
        90,
        cache_read=500,
    )
)
adv(500_000_000)

# ---- Task: orchestrator (parent=None), cache_gap (real premium, anthropic) ----
spans.append(agent_span("orchestrator", None, TRACE, t, 20_000_000_000, "orchestrator"))
spans.append(
    chat_span(
        "orch-c0",
        "orchestrator",
        TRACE,
        t,
        400_000_000,
        "anthropic",
        "claude-sonnet-4-6",
        600,
        80,
        cache_creation=1200,
    )
)
adv(500_000_000)
spans.append(
    chat_span(
        "orch-c1", "orchestrator", TRACE, t, 400_000_000, "anthropic", "claude-sonnet-4-6", 650, 70
    )
)
adv(500_000_000)
spans.append(
    chat_span(
        "orch-c2", "orchestrator", TRACE, t, 400_000_000, "anthropic", "claude-sonnet-4-6", 700, 90
    )
)
adv(500_000_000)

# ---- Task: research-lead (parent=orchestrator) direct calls + 3 nested siblings ----
spans.append(agent_span("research-lead", "orchestrator", TRACE, t, 18_000_000_000, "research-lead"))
spans.append(
    chat_span(
        "rl-c0", "research-lead", TRACE, t, 400_000_000, "anthropic", "claude-sonnet-4-6", 900, 200
    )
)
adv(500_000_000)

# -- nested sibling: research-sub-agent-A (parent=research-lead), retrieval_thrash --
spans.append(agent_span("sub-agent-a", "research-lead", TRACE, t, 6_000_000_000, "sub-agent-a"))
at = t
web_queries = [
    "climate policy renewable subsidies",
    "renewable subsidies climate policy",
    "climate subsidies policy renewable",
    "policy climate renewable subsidies",
    "subsidies renewable climate policy",
]
for i, q in enumerate(web_queries):
    spans.append(
        chat_span(
            f"suba-l{i}",
            "sub-agent-a",
            TRACE,
            at,
            300_000_000,
            "anthropic",
            "claude-sonnet-4-6",
            400,
            70,
        )
    )
    spans.append(
        tool_span(
            f"suba-t{i}",
            "sub-agent-a",
            TRACE,
            at + 300_000_000,
            300_000_000,
            "search_web",
            {"query": q},
            "No relevant results found.",
        )
    )
    at += 900_000_000
adv(6_100_000_000)

# -- nested sibling: research-sub-agent-B (parent=research-lead), genuinely productive --
spans.append(agent_span("sub-agent-b", "research-lead", TRACE, t, 4_000_000_000, "sub-agent-b"))
bt = t
narrowing = [
    (
        "search_web",
        {"q": "asyncio deadlock"},
        "Common causes: awaiting a lock already held by the same task.",
    ),
    (
        "search_web",
        {"q": "asyncio double lock same task"},
        "Reentrant asyncio.Lock isn't supported; use asyncio.Semaphore instead.",
    ),
]
for i, (name, args, result) in enumerate(narrowing):
    spans.append(
        chat_span(
            f"subb-l{i}",
            "sub-agent-b",
            TRACE,
            bt,
            300_000_000,
            "anthropic",
            "claude-sonnet-4-6",
            500 + i * 200,
            90,
        )
    )
    spans.append(
        tool_span(
            f"subb-t{i}", "sub-agent-b", TRACE, bt + 300_000_000, 300_000_000, name, args, result
        )
    )
    bt += 900_000_000
# final answer, chat-only -> reached_success
spans.append(
    chat_span(
        "subb-l2",
        "sub-agent-b",
        TRACE,
        bt,
        400_000_000,
        "anthropic",
        "claude-sonnet-4-6",
        1000,
        150,
    )
)
adv(4_100_000_000)

# -- nested sibling: summarizer (parent=research-lead), STALLED, never recovers --
spans.append(agent_span("summarizer", "research-lead", TRACE, t, 7_000_000_000, "summarizer"))
st = t
STALL_RESULT = "chunk summary: no new information beyond prior summary"
for k in range(6):
    spans.append(
        chat_span(
            f"summ-l{k}",
            "summarizer",
            TRACE,
            st,
            300_000_000,
            "anthropic",
            "claude-sonnet-4-6",
            1800 + k * 500,
            25,
        )
    )
    spans.append(
        tool_span(
            f"summ-t{k}",
            "summarizer",
            TRACE,
            st + 300_000_000,
            300_000_000,
            "summarize_chunk",
            {"chunk_id": k},
            STALL_RESULT,
        )
    )
    st += 700_000_000
adv(7_100_000_000)

trace = wrap_otlp_json(spans, service_name="research-agent")
out_path = Path(__file__).parent / "scenario3.json"
with open(out_path, "w") as f:
    json.dump(trace, f, indent=2)

print(f"wrote {out_path}: {len(spans)} spans")
