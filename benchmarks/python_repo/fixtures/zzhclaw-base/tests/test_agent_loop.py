"""Agent 主循环（agent/core.py:135-236）的行为测试。

这一层是 agent 的心脏：流式拼装、工具编排、错误自愈、轮次兜底。
所有用例用 FakeLLM 驱动，零网络、零成本。
"""

import json

import pytest
from fake_llm import ScriptExhausted, delta, tc_delta, text, tool_call


def roles(msgs):
    return [m["role"] for m in msgs]


def branch_messages(agent):
    """取会话分支里的原始 Message 列表（不是发给 LLM 的裁剪视图）。"""
    return agent.session_manager.current_session.current_branch.messages


def assert_tool_pairs_complete(messages):
    """OpenAI function calling 的硬约束：每个 assistant.tool_calls 的 id
    都必须有对应的 tool 消息，否则后续请求直接 400。"""
    tool_ids = {m.tool_call_id for m in messages if m.role == "tool"}
    for msg in messages:
        if msg.role == "assistant" and msg.tool_calls:
            for tc in msg.tool_calls:
                assert tc["id"] in tool_ids, f"tool_call {tc['id']} 缺少配对的 tool 结果"


# ===== 基本往返 =====

def test_plain_text_reply_is_returned_and_persisted(make_agent):
    agent = make_agent(["你好，我是 ZzhClaw"], system_prompt=None)

    assert agent.run("hi") == "你好，我是 ZzhClaw"
    assert [m.role for m in branch_messages(agent)] == ["user", "assistant"]


def test_system_prompt_injected_once_on_first_turn(make_agent):
    agent = make_agent(["a", "b"])

    agent.run("第一句")
    agent.run("第二句")

    messages = branch_messages(agent)
    assert messages[0].role == "system"
    assert sum(1 for m in messages if m.role == "system") == 1, "system prompt 不应重复注入"


def test_run_creates_session_if_missing(make_agent, session_manager):
    agent = make_agent(["ok"])
    assert session_manager.current_session is None

    agent.run("hi")

    assert session_manager.current_session is not None


# ===== 流式拼装 =====

def test_streamed_content_is_reassembled_and_pushed_per_token(make_agent):
    agent = make_agent([text("上下文压缩已完成", chunk=4)], system_prompt=None)

    tokens = []
    assert agent.run("继续", on_token=tokens.append) == "上下文压缩已完成"
    assert tokens == ["上下文压", "缩已完成"]


def test_tokens_are_not_pushed_for_tool_call_deltas(make_agent, stub_tools):
    agent = make_agent([tool_call("read_file", '{"path": "a.txt"}'), "done"], system_prompt=None)

    tokens = []
    agent.run("读", on_token=tokens.append)

    assert tokens == ["done"]


def test_tool_call_arguments_are_concatenated_across_deltas(make_agent, stub_tools):
    long_args = json.dumps({"path": "deep/nested/dir/file.txt", "content": "x" * 40})
    agent = make_agent([tool_call("write_file", long_args, arg_chunk=7), "写好了"], system_prompt=None)

    agent.run("写文件")

    name, args = stub_tools.calls[0]
    assert name == "write_file"
    assert args == json.loads(long_args)


def test_multiple_tool_calls_are_sorted_by_index(make_agent, stub_tools):
    """模型可能先吐 index=1 的片段；Agent 需按 index 归位并保序传给工具层。"""
    turn = [
        delta(tool_calls=[tc_delta(1, call_id="call_b", name="read_file", arguments="")]),
        delta(tool_calls=[tc_delta(1, arguments='{"path": "b"}')]),
        delta(tool_calls=[tc_delta(0, call_id="call_a", name="read_file", arguments="")]),
        delta(tool_calls=[tc_delta(0, arguments='{"path": "a"}')]),
    ]
    agent = make_agent([turn, "两个都读了"], system_prompt=None)

    agent.run("读两个")

    assert [args["path"] for _, args in stub_tools.calls] == ["a", "b"]


def test_tool_call_without_name_is_dropped(make_agent, stub_tools):
    """收尾片段常带空 tool_calls；无函数名的增量不该被当成调用。

    过滤后本轮既无文本也无有效工具，Agent 直接结束并返回空串。
    """
    turn = [
        delta(tool_calls=[tc_delta(0, call_id="call_x", name=None, arguments="")]),
        delta(tool_calls=[tc_delta(0, arguments='{"path": "a"}')]),
    ]
    agent = make_agent([turn], system_prompt=None)

    assert agent.run("hi") == ""
    assert stub_tools.calls == []
    assert len(agent.llm.calls) == 1, "被过滤的空 tool_call 不应触发新一轮请求"
    assert branch_messages(agent)[1].tool_calls is None


def test_empty_stream_returns_empty_string(make_agent):
    agent = make_agent([[]], system_prompt=None)
    assert agent.run("hi") == ""


# ===== 工具调用与错误自愈 =====

def test_tool_result_feeds_next_llm_call(make_agent, stub_tools):
    stub_tools.results["read_file"] = "文件内容是 42"
    agent = make_agent([tool_call("read_file", '{"path": "a.txt"}'), "内容是 42"], system_prompt=None)

    assert agent.run("读 a.txt") == "内容是 42"

    second_call_messages = agent.llm.calls[1]["messages"]
    tool_msgs = [m for m in second_call_messages if m["role"] == "tool"]
    assert tool_msgs[0]["content"] == "文件内容是 42"


def test_bad_json_is_reported_to_model_and_self_heals(make_agent, stub_tools):
    """模型吐出被截断的 JSON 时，错误要作为工具结果回传，让模型自己重试。"""
    broken = '{"path": "a.txt'
    agent = make_agent(
        [
            tool_call("read_file", broken),
            tool_call("read_file", '{"path": "a.txt"}', call_id="call_ok"),
            "读好了",
        ],
        system_prompt=None,
    )
    stub_tools.results["read_file"] = "内容"

    assert agent.run("读 a.txt") == "读好了"

    messages = branch_messages(agent)
    tool_msgs = [m for m in messages if m.role == "tool"]
    assert "工具参数解析失败" in tool_msgs[0].content
    assert broken in tool_msgs[0].content, "原始参数要一并回传，模型才知道怎么改"
    assert len(stub_tools.calls) == 1, "坏参数不应被执行"
    assert_tool_pairs_complete(messages)


def test_non_object_json_arguments_are_rejected(make_agent, stub_tools):
    agent = make_agent(
        [tool_call("read_file", "[1, 2, 3]"), "算了"],
        system_prompt=None,
    )

    agent.run("读")

    assert "预期 dict，实际得到 list" in branch_messages(agent)[2].content
    assert stub_tools.calls == []


def test_empty_arguments_default_to_empty_dict(make_agent, stub_tools):
    agent = make_agent([tool_call("glob_files", ""), "完成"], system_prompt=None)

    agent.run("列文件")

    assert stub_tools.calls == [("glob_files", {})]


def test_tool_exception_still_produces_paired_result(make_agent, stub_tools):
    """工具抛异常必须被兜成字符串，否则 tool_call_id 断配、整段会话报废。"""
    stub_tools.raises["run_bash"] = RuntimeError("磁盘炸了")
    agent = make_agent([tool_call("run_bash", '{"command": "ls"}'), "收到错误了"], system_prompt=None)

    assert agent.run("列目录") == "收到错误了"

    tool_msg = [m for m in branch_messages(agent) if m.role == "tool"][0]
    assert tool_msg.content.startswith("工具执行异常:")
    assert "RuntimeError" in tool_msg.content and "磁盘炸了" in tool_msg.content
    assert_tool_pairs_complete(branch_messages(agent))


# ===== 轮次上限 =====

def test_max_iterations_stops_runaway_tool_loop(make_agent, stub_tools):
    agent = make_agent(
        [tool_call("read_file", '{"path": "a"}'), tool_call("read_file", '{"path": "b"}')],
        system_prompt=None,
    )

    result = agent.run("无限读", max_iterations=2)

    assert "已达到单次交互工具调用轮次上限 (2)" in result
    assert len(stub_tools.calls) == 2
    assert branch_messages(agent)[-1].role == "assistant"


def test_exhausted_script_surfaces_as_error(make_agent, stub_tools):
    """脚本没写够说明被测逻辑多绕了一圈；FakeLLM 要报警而不是静默挂住。"""
    agent = make_agent([tool_call("read_file", '{"path": "a"}')], system_prompt=None)

    with pytest.raises(ScriptExhausted):
        agent.run("只给一轮工具，模型却没有收尾回复")


# ===== 发给 LLM 的上下文 =====

def test_tools_schema_is_passed_to_llm(make_agent):
    agent = make_agent(["hi"], system_prompt=None)

    agent.run("你好")

    tools = agent.llm.calls[0]["tools"]
    assert {t["function"]["name"] for t in tools} >= {"read_file", "write_file", "run_bash"}


def test_windowed_messages_reach_llm_not_raw_history(make_agent, stub_tools):
    agent = make_agent([tool_call("read_file", '{"path": "a"}'), "好了"], system_prompt=None)

    agent.run("读")

    second = agent.llm.calls[1]["messages"]
    assert roles(second) == ["user", "assistant", "tool"]
    assert second[1]["tool_calls"][0]["id"] == "call_0_read_file"


# ===== UI 回调管线（TUI/Web 靠这几个钩子渲染）=====

def test_tool_call_and_result_callbacks_fire_in_order(make_agent, stub_tools):
    agent = make_agent([tool_call("grep_files", '{"pattern": "x"}'), "结束"], system_prompt=None)
    events = []

    agent.run(
        "搜一下",
        on_tool_call=lambda name, args: events.append(("call", name, args)),
        on_tool_result=lambda name, result: events.append(("result", name, result)),
        on_token=lambda t: events.append(("token", t)),
    )

    assert events == [
        ("call", "grep_files", {"pattern": "x"}),
        ("result", "grep_files", "[stub] grep_files 已执行"),
        ("token", "结束"),
    ]


def test_parse_error_is_also_reported_to_the_ui(make_agent, stub_tools):
    """坏参数没有 on_tool_call，但必须有 on_tool_result，否则 UI 会停在"执行中"。"""
    agent = make_agent([tool_call("read_file", "{oops"), "重试失败"], system_prompt=None)
    calls, results = [], []

    agent.run("读", on_tool_call=lambda n, a: calls.append(n),
              on_tool_result=lambda n, r: results.append((n, r)))

    assert calls == []
    assert results[0][0] == "read_file" and "工具参数解析失败" in results[0][1]


def test_refused_tool_is_not_announced_as_started(make_agent, stub_tools):
    agent = make_agent([tool_call("run_bash", "{}"), "好吧"], system_prompt=None)
    calls = []

    agent.run("执行", on_tool_call=lambda n, a: calls.append(n), confirm_tool=lambda n, a: False)

    assert calls == []


# ===== 会话代理方法 =====

def test_agent_delegates_session_operations(make_agent, session_manager, tmp_path):
    agent = make_agent(["回复"], system_prompt=None)

    agent.new_session("我的会话")
    agent.run("你好")
    session_id = session_manager.current_session.id
    agent.save()

    assert [s["name"] for s in agent.list_sessions()] == ["我的会话"]
    assert agent.load_session(session_id) is True
    assert agent.load_session("不存在") is False

    agent.fork_branch(0, "分叉")
    assert session_manager.current_session.current_branch.name == "分叉"
