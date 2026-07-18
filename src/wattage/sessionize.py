"""Raw spans -> Trace(Session(Task(Loop(Iteration)))), per doc §7.4/§5.6.

Sessions are grouped by trace_id. Within a session, *every* `invoke_agent`
span becomes its own Task boundary — including nested ones (an agent
invoking a sub-agent), so each gets its own convergence analysis rather than
being flattened into its parent's loop (Phase 2's "fully implemented" loop
reconstruction). Call spans not claimed by any agent span (either because
there are no agent spans at all, or because some calls sit outside every
agent's subtree) fall into a final catch-all task so nothing is silently
dropped.

Within a task, the loop-reconstruction fallback heuristic (§5.6) applies: a
chat span opens a new iteration, and any execute_tool/embeddings spans that
follow before the next chat span join that iteration. If the task's call
spans include any tool/retrieval activity, the whole sequence becomes a
single Loop of iterations; a task with pure chat (no tool/retrieval calls at
all) has no loop — those calls sit directly on Task.llm_calls.

Loop.reached_success is set by a structural heuristic (see
_infer_reached_success) — not a semantic guarantee.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from wattage.models import Iteration, Loop, RawSpan, Session, SpanKind, Task, Trace
from wattage.normalize import normalize_llm_call, normalize_retrieval_call, normalize_tool_call

_CALL_KINDS = {SpanKind.chat, SpanKind.execute_tool, SpanKind.embeddings}


def sessionize(spans: Iterable[RawSpan], source: str) -> Trace:
    all_spans = list(spans)
    by_trace: dict[str, list[RawSpan]] = defaultdict(list)
    for span in all_spans:
        by_trace[span.trace_id or span.span_id].append(span)

    sessions = [
        _build_session(trace_id, trace_spans) for trace_id, trace_spans in by_trace.items()
    ]
    return Trace(source=source, sessions=sessions)


def _build_session(session_id: str, spans: list[RawSpan]) -> Session:
    by_id = {s.span_id: s for s in spans}
    children: dict[str | None, list[str]] = defaultdict(list)
    for s in spans:
        children[s.parent_span_id].append(s.span_id)

    agent_ids = {s.span_id for s in spans if s.kind == SpanKind.invoke_agent}
    agent_spans = sorted((by_id[sid] for sid in agent_ids), key=lambda s: s.start_ns)

    tasks: list[Task] = []
    claimed: set[str] = set()
    for i, agent_span in enumerate(agent_spans):
        descendant_ids = _descendant_call_ids(agent_span.span_id, children, agent_ids)
        call_spans = sorted(
            (by_id[cid] for cid in descendant_ids if by_id[cid].kind in _CALL_KINDS),
            key=lambda s: s.start_ns,
        )
        claimed.update(cid for cid in descendant_ids)
        tasks.append(_build_task(f"{session_id}:task{i}", call_spans))

    leftover = sorted(
        (s for s in spans if s.kind in _CALL_KINDS and s.span_id not in claimed),
        key=lambda s: s.start_ns,
    )
    if leftover:
        tasks.append(_build_task(f"{session_id}:task{len(tasks)}", leftover))

    return Session(session_id=session_id, tasks=tasks)


def _descendant_call_ids(
    root_id: str, children: dict[str | None, list[str]], agent_ids: set[str]
) -> list[str]:
    """Descendants of root_id, not recursing past a *nested* agent span (its
    subtree belongs to its own task, not this one)."""
    result: list[str] = []
    stack = list(children.get(root_id, []))
    while stack:
        cid = stack.pop()
        result.append(cid)
        if cid not in agent_ids:
            stack.extend(children.get(cid, []))
    return result


def _build_task(task_id: str, call_spans: list[RawSpan]) -> Task:
    has_tool_or_retrieval = any(
        s.kind in (SpanKind.execute_tool, SpanKind.embeddings) for s in call_spans
    )
    if not has_tool_or_retrieval:
        llm_calls = [normalize_llm_call(s) for s in call_spans if s.kind == SpanKind.chat]
        return Task(task_id=task_id, llm_calls=llm_calls)

    groups: list[list[RawSpan]] = []
    for s in call_spans:
        if s.kind == SpanKind.chat or not groups:
            groups.append([s])
        else:
            groups[-1].append(s)

    iterations = []
    for idx, group in enumerate(groups):
        iteration = Iteration(index=idx)
        for s in group:
            if s.kind == SpanKind.chat:
                iteration.llm_calls.append(normalize_llm_call(s))
            elif s.kind == SpanKind.execute_tool:
                iteration.tool_calls.append(normalize_tool_call(s))
            elif s.kind == SpanKind.embeddings:
                iteration.retrievals.append(normalize_retrieval_call(s))
        iterations.append(iteration)

    loop = Loop(
        loop_id=f"{task_id}:loop0",
        iterations=iterations,
        reached_success=_infer_reached_success(iterations),
    )
    return Task(task_id=task_id, loops=[loop])


def _infer_reached_success(iterations: list[Iteration]) -> bool:
    """Structural proxy, not a semantic guarantee: a loop "reached success"
    if its last iteration produced LLM output with no further tool call
    pending — i.e. the agent stopped calling tools rather than being cut off
    mid-action. Genuine goal-completion detection needs semantics (an
    explicit goal signal or the optional judge), which this doesn't have.
    """
    if not iterations:
        return False
    last = iterations[-1]
    return bool(last.llm_calls) and not last.tool_calls
