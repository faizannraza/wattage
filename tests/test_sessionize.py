from wattage.models import RawSpan, SpanKind
from wattage.sessionize import sessionize


def _chat(span_id: str, parent_id: str | None, trace_id: str, start: int) -> RawSpan:
    return RawSpan(
        span_id=span_id,
        parent_span_id=parent_id,
        trace_id=trace_id,
        name="chat",
        kind=SpanKind.chat,
        attributes={
            "gen_ai.provider.name": "anthropic",
            "gen_ai.request.model": "claude-sonnet-4-6",
            "gen_ai.usage.input_tokens": 100,
            "gen_ai.usage.output_tokens": 10,
        },
        start_ns=start,
        end_ns=start + 1,
    )


def _tool(span_id: str, parent_id: str | None, trace_id: str, start: int) -> RawSpan:
    return RawSpan(
        span_id=span_id,
        parent_span_id=parent_id,
        trace_id=trace_id,
        name="execute_tool search_docs",
        kind=SpanKind.execute_tool,
        attributes={"gen_ai.tool.name": "search_docs"},
        start_ns=start,
        end_ns=start + 1,
    )


def test_pure_chat_task_has_no_loop() -> None:
    spans = [_chat("c1", None, "trace-B", 0)]
    trace = sessionize(spans, source="synthetic")

    task = trace.sessions[0].tasks[0]
    assert task.loops == []
    assert len(task.llm_calls) == 1


def test_repeated_chat_tool_cycles_form_one_loop_with_correct_iterations() -> None:
    agent = RawSpan(
        span_id="agent-1",
        parent_span_id=None,
        trace_id="trace-A",
        name="invoke_agent support-bot",
        kind=SpanKind.invoke_agent,
        start_ns=0,
        end_ns=100,
    )
    spans = [
        agent,
        _chat("chat-1", "agent-1", "trace-A", 1),
        _tool("tool-1", "agent-1", "trace-A", 10),
        _chat("chat-2", "agent-1", "trace-A", 15),
        _tool("tool-2", "agent-1", "trace-A", 25),
        _chat("chat-3", "agent-1", "trace-A", 30),
    ]
    trace = sessionize(spans, source="synthetic")

    assert len(trace.sessions) == 1
    task = trace.sessions[0].tasks[0]
    assert task.llm_calls == []
    assert len(task.loops) == 1

    loop = task.loops[0]
    assert len(loop.iterations) == 3
    assert [len(it.tool_calls) for it in loop.iterations] == [1, 1, 0]
    assert [len(it.llm_calls) for it in loop.iterations] == [1, 1, 1]
    assert [it.index for it in loop.iterations] == [0, 1, 2]


def test_multiple_trace_ids_become_separate_sessions() -> None:
    spans = [_chat("c1", None, "trace-1", 0), _chat("c2", None, "trace-2", 0)]
    trace = sessionize(spans, source="synthetic")
    assert {s.session_id for s in trace.sessions} == {"trace-1", "trace-2"}


def _agent(span_id: str, parent_id: str | None, trace_id: str, start: int, end: int) -> RawSpan:
    return RawSpan(
        span_id=span_id,
        parent_span_id=parent_id,
        trace_id=trace_id,
        name="invoke_agent",
        kind=SpanKind.invoke_agent,
        start_ns=start,
        end_ns=end,
    )


def test_loop_ending_in_chat_only_iteration_is_inferred_as_reached_success() -> None:
    agent = _agent("agent-1", None, "trace-A", 0, 100)
    spans = [
        agent,
        _chat("chat-1", "agent-1", "trace-A", 1),
        _tool("tool-1", "agent-1", "trace-A", 10),
        _chat("chat-2", "agent-1", "trace-A", 15),
    ]
    trace = sessionize(spans, source="synthetic")
    loop = trace.sessions[0].tasks[0].loops[0]
    assert loop.reached_success is True


def test_loop_ending_mid_tool_call_is_not_inferred_as_reached_success() -> None:
    agent = _agent("agent-1", None, "trace-A", 0, 100)
    spans = [
        agent,
        _chat("chat-1", "agent-1", "trace-A", 1),
        _tool("tool-1", "agent-1", "trace-A", 10),
        _chat("chat-2", "agent-1", "trace-A", 15),
        _tool("tool-2", "agent-1", "trace-A", 20),
    ]
    trace = sessionize(spans, source="synthetic")
    loop = trace.sessions[0].tasks[0].loops[0]
    assert loop.reached_success is False


def test_nested_agent_span_becomes_its_own_task() -> None:
    outer = _agent("outer-agent", None, "trace-A", 0, 100)
    inner = _agent("inner-agent", "outer-agent", "trace-A", 10, 50)
    spans = [
        outer,
        _chat("outer-chat", "outer-agent", "trace-A", 1),
        inner,
        _chat("inner-chat", "inner-agent", "trace-A", 11),
    ]
    trace = sessionize(spans, source="synthetic")

    tasks = trace.sessions[0].tasks
    assert len(tasks) == 2
    # Each task claims only its own agent's direct call, not the nested one's.
    all_llm_span_ids = {c.span_id for t in tasks for c in t.llm_calls}
    assert all_llm_span_ids == {"outer-chat", "inner-chat"}
    outer_task = next(t for t in tasks if any(c.span_id == "outer-chat" for c in t.llm_calls))
    assert all(c.span_id != "inner-chat" for c in outer_task.llm_calls)


def test_orphan_calls_outside_any_agent_span_get_a_catch_all_task() -> None:
    agent = _agent("agent-1", None, "trace-A", 0, 100)
    spans = [
        agent,
        _chat("agent-chat", "agent-1", "trace-A", 1),
        _chat("orphan-chat", None, "trace-A", 200),  # sibling of the agent span, not under it
    ]
    trace = sessionize(spans, source="synthetic")

    tasks = trace.sessions[0].tasks
    assert len(tasks) == 2
    all_llm_span_ids = {c.span_id for t in tasks for c in t.llm_calls}
    assert all_llm_span_ids == {"agent-chat", "orphan-chat"}
