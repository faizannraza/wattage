"""Trace -> a JSON-serializable tree for the flame graph (doc §3.2/§7.7's
"burn map"): session -> task -> loop -> iteration -> call -> token-class
segment.

Sized by *tokens*, not dollars: tool/retrieval calls don't carry a priced
Cost the way LLMCall does (tool execution isn't billed in tokens the same
way), so dollars can't be the universal sizing metric across every node
type without fabricating a number for tool nodes. Tokens are a real,
measurable quantity everywhere, so they're what determines rectangle width;
dollar figures are attached wherever they're real (every LLM token-class
segment) and simply absent — not estimated, not guessed — on tool/retrieval
nodes.

Only the innermost "segment" nodes (input/cache_read/cache_creation/
reasoning/output/tool_io) carry a `category` used for categorical coloring;
every ancestor (session/task/loop/iteration/call) is a structural grouping
rendered in a neutral shade, not a token-source category itself — the doc's
illustrative category names (system prompt / re-sent history / retrieved
context) imply a per-call prefix breakdown this codebase can't measure
without content capture + diffing (prefix_churn approximates it in
aggregate for detection, not per-call for display), so this renders the
token classes we can actually measure (input/cache_read/cache_creation/
reasoning/output) plus a combined tool_io class, not the doc's illustrative
names.
"""

from __future__ import annotations

from typing import Any

from wattage.models import Iteration, LLMCall, Loop, RetrievalCall, Session, Task, ToolCall, Trace

_CHARS_PER_TOKEN = 4


def _segment(category: str, tokens: int, dollars: float) -> dict[str, Any]:
    return {
        "name": category,
        "kind": "segment",
        "category": category,
        "value": tokens,
        "tokens": tokens,
        "dollars": dollars,
        "children": [],
    }


def _llm_node(call: LLMCall, label: str) -> dict[str, Any]:
    usage = call.usage
    cost = call.cost
    children = [
        seg
        for seg in (
            _segment("input", usage.input, cost.input),
            _segment("cache_read", usage.cache_read, cost.cache_read),
            _segment("cache_creation", usage.cache_creation, cost.cache_creation),
            _segment("reasoning", usage.reasoning, cost.reasoning),
            _segment("output", usage.output, cost.output),
        )
        if seg["tokens"] > 0
    ]
    return {
        "name": label,
        "kind": "llm",
        "model": call.model,
        "value": usage.total(),
        "tokens": usage.total(),
        "dollars": cost.total,
        "children": children,
    }


def _tool_node(tc: ToolCall) -> dict[str, Any]:
    tokens = len(tc.result) // _CHARS_PER_TOKEN if tc.result else 0
    children = [_segment("tool_io", tokens, 0.0)] if tokens > 0 else []
    return {
        "name": tc.name,
        "kind": "tool",
        "model": None,
        "value": tokens,
        "tokens": tokens,
        "dollars": None,
        "children": children,
    }


def _retrieval_node(rc: RetrievalCall) -> dict[str, Any]:
    tokens = sum(
        len(str(chunk.get("text", ""))) // _CHARS_PER_TOKEN
        for chunk in rc.chunks
        if isinstance(chunk, dict)
    )
    children = [_segment("tool_io", tokens, 0.0)] if tokens > 0 else []
    return {
        "name": rc.query or "retrieval",
        "kind": "retrieval",
        "model": None,
        "value": tokens,
        "tokens": tokens,
        "dollars": None,
        "children": children,
    }


def _iteration_node(iteration: Iteration, index: int) -> dict[str, Any]:
    children: list[dict[str, Any]] = []
    for call in iteration.llm_calls:
        children.append(_llm_node(call, label=call.model))
    for tc in iteration.tool_calls:
        children.append(_tool_node(tc))
    for rc in iteration.retrievals:
        children.append(_retrieval_node(rc))
    tokens = sum(c["tokens"] for c in children)
    return {
        "name": f"iteration {index}",
        "kind": "iteration",
        "model": None,
        "value": tokens,
        "tokens": tokens,
        "dollars": sum(c["dollars"] for c in children if c["dollars"] is not None),
        "children": children,
    }


def _loop_node(loop: Loop) -> dict[str, Any]:
    children = [_iteration_node(it, i) for i, it in enumerate(loop.iterations)]
    tokens = sum(c["tokens"] for c in children)
    return {
        "name": loop.loop_id,
        "kind": "loop",
        "model": None,
        "value": tokens,
        "tokens": tokens,
        "dollars": sum(c["dollars"] for c in children if c["dollars"] is not None),
        "children": children,
    }


def _task_node(task: Task) -> dict[str, Any]:
    children: list[dict[str, Any]] = []
    for call in task.llm_calls:
        children.append(_llm_node(call, label=call.model))
    for loop in task.loops:
        children.append(_loop_node(loop))
    tokens = sum(c["tokens"] for c in children)
    return {
        "name": task.task_id,
        "kind": "task",
        "model": None,
        "value": tokens,
        "tokens": tokens,
        "dollars": sum(c["dollars"] for c in children if c["dollars"] is not None),
        "children": children,
    }


def _session_node(session: Session) -> dict[str, Any]:
    children = [_task_node(t) for t in session.tasks]
    tokens = sum(c["tokens"] for c in children)
    return {
        "name": session.session_id,
        "kind": "session",
        "model": None,
        "value": tokens,
        "tokens": tokens,
        "dollars": sum(c["dollars"] for c in children if c["dollars"] is not None),
        "children": children,
    }


def build_tree(trace: Trace) -> dict[str, Any]:
    children = [_session_node(s) for s in trace.sessions]
    tokens = sum(c["tokens"] for c in children)
    return {
        "name": trace.source,
        "kind": "trace",
        "model": None,
        "value": tokens,
        "tokens": tokens,
        "dollars": sum(c["dollars"] for c in children if c["dollars"] is not None),
        "children": children,
    }
