"""Raw spans -> Trace(Session(Task(Loop(Iteration)))), per doc §7.4/§5.6.

Sessions are grouped by trace_id. Within a session, top-level `invoke_agent`
spans become Task boundaries (or the whole session is one implicit task when
no agent span is present). Within a task, the loop-reconstruction fallback
heuristic (§5.6) applies: a chat span opens a new iteration, and any
execute_tool/embeddings spans that follow before the next chat span join that
iteration. If the task's call spans include any tool/retrieval activity, the
whole sequence becomes a single Loop of iterations; a task with pure chat
(no tool/retrieval calls at all) has no loop — those calls sit directly on
Task.llm_calls.
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
    top_agent_spans = sorted(
        (by_id[sid] for sid in agent_ids if not _has_ancestor_in(by_id[sid], by_id, agent_ids)),
        key=lambda s: s.start_ns,
    )

    tasks: list[Task] = []
    if top_agent_spans:
        for i, agent_span in enumerate(top_agent_spans):
            descendant_ids = _descendant_ids(agent_span.span_id, children)
            call_spans = sorted(
                (by_id[cid] for cid in descendant_ids if by_id[cid].kind in _CALL_KINDS),
                key=lambda s: s.start_ns,
            )
            tasks.append(_build_task(f"{session_id}:task{i}", call_spans))
    else:
        call_spans = sorted((s for s in spans if s.kind in _CALL_KINDS), key=lambda s: s.start_ns)
        tasks.append(_build_task(f"{session_id}:task0", call_spans))

    return Session(session_id=session_id, tasks=tasks)


def _has_ancestor_in(span: RawSpan, by_id: dict[str, RawSpan], ids: set[str]) -> bool:
    parent_id = span.parent_span_id
    seen: set[str] = set()
    while parent_id is not None and parent_id in by_id and parent_id not in seen:
        if parent_id in ids:
            return True
        seen.add(parent_id)
        parent_id = by_id[parent_id].parent_span_id
    return False


def _descendant_ids(root_id: str, children: dict[str | None, list[str]]) -> list[str]:
    result: list[str] = []
    stack = list(children.get(root_id, []))
    while stack:
        cid = stack.pop()
        result.append(cid)
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

    loop = Loop(loop_id=f"{task_id}:loop0", iterations=iterations)
    return Task(task_id=task_id, loops=[loop])
