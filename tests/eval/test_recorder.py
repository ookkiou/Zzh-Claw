import json

from fake_llm import tool_call

from zzhclaw.eval import TrajectoryRecorder


def test_recorder_assigns_sequences_and_preserves_extra_metadata(tmp_path):
    recorder = TrajectoryRecorder()

    recorder({"event_type": "agent_start", "custom": "value"})
    recorder.record(
        "tool_call",
        tool_call_id="call-1",
        tool_name="read_file",
        arguments={"path": "app.py"},
        metadata={"iteration": 1},
    )

    assert [event.sequence for event in recorder.events] == [0, 1]
    assert recorder.events[0].metadata["custom"] == "value"
    assert recorder.tool_call_count == 1
    assert recorder.max_iteration == 1

    path = recorder.write(tmp_path / "trace.jsonl")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["event_type"] for row in rows] == ["agent_start", "tool_call"]


def test_agent_emits_structured_lifecycle_events(make_agent, stub_tools):
    agent = make_agent(
        [tool_call("read_file", '{"path":"app.py"}', call_id="call-1"), "完成"],
        system_prompt=None,
        permission_mode="auto",
    )
    recorder = TrajectoryRecorder()

    assert agent.run("读取", on_event=recorder) == "完成"

    assert [event.event_type for event in recorder.events] == [
        "agent_start",
        "tool_call",
        "tool_result",
        "agent_final",
    ]
    call = recorder.events[1]
    result = recorder.events[2]
    assert call.tool_call_id == result.tool_call_id == "call-1"
    assert call.arguments == {"path": "app.py"}
    assert result.result == "[stub] read_file 已执行"
    assert result.duration_ms is not None and result.duration_ms >= 0


def test_bad_tool_json_is_visible_in_trace(make_agent, stub_tools):
    agent = make_agent(
        [tool_call("read_file", "{broken", call_id="bad"), "已处理错误"],
        system_prompt=None,
        permission_mode="auto",
    )
    recorder = TrajectoryRecorder()

    agent.run("读取", on_event=recorder)

    call = next(event for event in recorder.events if event.event_type == "tool_call")
    result = next(
        event for event in recorder.events if event.event_type == "tool_result"
    )
    assert call.arguments is None
    assert call.error
    assert "工具参数解析失败" in result.result
    assert stub_tools.calls == []


def test_llm_failure_emits_agent_error(make_agent):
    class BrokenLLM:
        def chat_stream(self, messages, tools=None):
            raise RuntimeError("service unavailable")

        def summarize(self, existing_summary, messages):
            return ""

    agent = make_agent(llm=BrokenLLM(), system_prompt=None)
    recorder = TrajectoryRecorder()

    try:
        agent.run("任务", on_event=recorder)
    except RuntimeError:
        pass

    assert recorder.events[-1].event_type == "agent_error"
    assert "service unavailable" in recorder.events[-1].error
