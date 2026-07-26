"""Scenario 1: e-commerce customer support multi-agent system.
See GROUND_TRUTH.md for the full spec and expected findings.

Structure: one top-level "orchestrator" invoke_agent span, with its own 4
direct chat calls AND 3 nested specialist sub-agent spans as children
(2-level nesting, 3 siblings) -- billing-agent, technical-agent,
escalation-agent.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from span_builder import agent_span, chat_span, tool_span, wrap_otlp_json  # noqa: E402

TRACE = "trace-cs-001"
spans = []
t = 0


def adv(ns):
    global t
    t += ns


ORCH_START = t
spans.append(agent_span("orchestrator", None, TRACE, ORCH_START, 30_000_000_000, "orchestrator"))

# ---- orchestrator's own 4 direct calls (children of "orchestrator", not of any sub-agent) ----
spans.append(
    chat_span(
        "orch-c0",
        "orchestrator",
        TRACE,
        t,
        800_000_000,
        "anthropic",
        "claude-sonnet-4-6",
        1200,
        150,
    )
)
adv(900_000_000)
spans.append(
    chat_span(
        "orch-c1",
        "orchestrator",
        TRACE,
        t,
        800_000_000,
        "anthropic",
        "claude-sonnet-4-6",
        1400,
        140,
    )
)
adv(900_000_000)
# reasoning-heavy, small-output call -> reasoning_overspend bait
spans.append(
    chat_span(
        "orch-c2",
        "orchestrator",
        TRACE,
        t,
        2_000_000_000,
        "anthropic",
        "claude-sonnet-4-6",
        1600,
        80,
        reasoning_tokens=900,
    )
)
adv(2_100_000_000)
spans.append(
    chat_span(
        "orch-c3",
        "orchestrator",
        TRACE,
        t,
        800_000_000,
        "anthropic",
        "claude-sonnet-4-6",
        1750,
        200,
    )
)
adv(900_000_000)

# ---- Task: billing-agent (nested under orchestrator), productive loop, reached_success ----
spans.append(agent_span("billing-agent", "orchestrator", TRACE, t, 6_000_000_000, "billing-agent"))
bt = t
spans.append(
    chat_span(
        "bill-l0",
        "billing-agent",
        TRACE,
        bt,
        400_000_000,
        "anthropic",
        "claude-sonnet-4-6",
        300,
        60,
    )
)
spans.append(
    tool_span(
        "bill-t0",
        "billing-agent",
        TRACE,
        bt + 400_000_000,
        300_000_000,
        "check_invoice",
        {"id": "INV-501"},
        "invoice found, total $84.20",
    )
)
bt += 900_000_000
spans.append(
    chat_span(
        "bill-l1",
        "billing-agent",
        TRACE,
        bt,
        400_000_000,
        "anthropic",
        "claude-sonnet-4-6",
        320,
        60,
    )
)
spans.append(
    tool_span(
        "bill-t1",
        "billing-agent",
        TRACE,
        bt + 400_000_000,
        300_000_000,
        "check_invoice",
        {"id": "INV-501"},
        "invoice found, total $84.20",
    )
)
bt += 900_000_000
spans.append(
    chat_span(
        "bill-l2",
        "billing-agent",
        TRACE,
        bt,
        400_000_000,
        "anthropic",
        "claude-sonnet-4-6",
        340,
        70,
    )
)
spans.append(
    tool_span(
        "bill-t2",
        "billing-agent",
        TRACE,
        bt + 400_000_000,
        300_000_000,
        "apply_refund",
        {"id": "INV-501", "amount": 84.2},
        "refund applied",
    )
)
bt += 900_000_000
# final answer, chat-only -> reached_success
spans.append(
    chat_span(
        "bill-l3",
        "billing-agent",
        TRACE,
        bt,
        500_000_000,
        "anthropic",
        "claude-sonnet-4-6",
        360,
        90,
    )
)
adv(6_100_000_000)

# ---- Task: technical-agent (nested), thrashing loop, flat cost, never recovers ----
spans.append(
    agent_span("technical-agent", "orchestrator", TRACE, t, 8_000_000_000, "technical-agent")
)
tt = t
for i in range(6):
    spans.append(
        chat_span(
            f"tech-l{i}",
            "technical-agent",
            TRACE,
            tt,
            300_000_000,
            "anthropic",
            "claude-haiku-4-5",
            500,
            50,
        )
    )
    spans.append(
        tool_span(
            f"tech-t{i}",
            "technical-agent",
            TRACE,
            tt + 300_000_000,
            200_000_000,
            "diagnose_connection",
            {"attempt": i},
            "still failing: timeout on port 443",
        )
    )
    tt += 550_000_000
adv(8_100_000_000)

# ---- Task: escalation-agent (nested): retrieval_thrash + cache_gap + verbosity ----
spans.append(
    agent_span("escalation-agent", "orchestrator", TRACE, t, 7_000_000_000, "escalation-agent")
)
et = t
kb_queries = [
    "billing dispute unresolved",
    "billing dispute unresolved escalation",
    "escalation billing dispute",
    "unresolved billing escalation path",
    "billing escalation unresolved dispute",
]
for i, q in enumerate(kb_queries):
    cache_creation = (
        1800 if i == 0 else 0
    )  # attempt caching once, never redeemed (cache_read=0 always)
    output_tok = 1400 if i == len(kb_queries) - 1 else 90  # final answer is way too verbose
    spans.append(
        chat_span(
            f"esc-l{i}",
            "escalation-agent",
            TRACE,
            et,
            400_000_000,
            "openai",
            "gpt-5.6-luna",
            600,
            output_tok,
            cache_creation=cache_creation,
        )
    )
    spans.append(
        tool_span(
            f"esc-t{i}",
            "escalation-agent",
            TRACE,
            et + 400_000_000,
            300_000_000,
            "search_kb",
            {"query": q},
            "no matching articles found",
        )
    )
    et += 900_000_000
adv(7_100_000_000)

trace = wrap_otlp_json(spans, service_name="customer-support-system")
out_path = Path(__file__).parent / "scenario1.json"
with open(out_path, "w") as f:
    json.dump(trace, f, indent=2)

print(f"wrote {out_path}: {len(spans)} spans")
