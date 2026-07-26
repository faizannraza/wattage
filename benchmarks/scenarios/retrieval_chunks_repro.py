"""Isolated repro for a real bug found via this directory's scenarios: does
retrieval_thrash fire on genuine SpanKind.embeddings spans with obviously
duplicate/low-yield content, the same way it already did via the
tool-name-heuristic path?

It didn't, before normalize.py's normalize_retrieval_call was fixed to
actually populate RetrievalCall.chunks (see CHANGELOG.md's 0.1.1 entry) --
this trace produced zero findings despite being structurally identical in
spirit to Scenario 1's escalation-agent (tool-name-heuristic retrieval,
which correctly fires retrieval_thrash on the same near-duplicate-query,
near-duplicate-result shape). Kept here as a permanent regression check:
single task, one agent, one loop, 5 embeddings iterations with
near-identical low-relevance content, using genuine embeddings-kind spans
instead of tool calls.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from span_builder import agent_span, chat_span, embeddings_span, wrap_otlp_json  # noqa: E402

TRACE = "trace-finding1-001"
spans = []
t = 0


def adv(ns):
    global t
    t += ns


spans.append(agent_span("rag-agent", None, TRACE, t, 5_000_000_000, "rag-agent"))
queries = [
    "renewable energy policy",
    "renewable energy policy update",
    "energy policy renewable update",
    "policy update renewable energy",
    "renewable policy energy update",
]
for i, q in enumerate(queries):
    spans.append(
        chat_span(
            f"c{i}", "rag-agent", TRACE, t, 300_000_000, "anthropic", "claude-sonnet-4-6", 400, 60
        )
    )
    adv(300_000_000)
    # Same obviously-duplicate chunk text every time, via a GENUINE embeddings span.
    spans.append(
        embeddings_span(
            f"e{i}",
            "rag-agent",
            TRACE,
            t,
            200_000_000,
            q,
            ["No new policy details found beyond prior summary."],
        )
    )
    adv(200_000_000)
    adv(100_000_000)

trace = wrap_otlp_json(spans, service_name="rag-agent")
out_path = Path(__file__).parent / "retrieval_chunks_repro.json"
with open(out_path, "w") as f:
    json.dump(trace, f, indent=2)

print(f"wrote {out_path}: {len(spans)} spans")
