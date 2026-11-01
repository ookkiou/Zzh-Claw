"""权限模式与用户确认（agent/core.py:47-61, 202-209）。

这一层的价值在于：拒绝路径也必须产生 tool 结果消息，否则 assistant.tool_calls
配不上对，整段会话之后的每一次请求都会被 API 拒掉。
"""

import pytest
from fake_llm import tool_call

from zzhclaw.agent import Agent


def branch_messages(agent):
    return agent.session_manager.current_session.current_branch.messages


def tool_results(agent):
    return [m for m in branch_messages(agent) if m.role == "tool"]


def assert_tool_pairs_complete(messages):
    tool_ids = {m.tool_call_id for m in messages if m.role == "tool"}
    for msg in messages:
        if msg.role == "assistant" and msg.tool_calls:
            for tc in msg.tool_calls:
                assert tc["id"] in tool_ids


@pytest.fixture
def asked():
    """记录被要求确认的工具，并默认全部放行。"""

    class Recorder:
        def __init__(self):
            self.names = []
            self.approve = True

        def confirm(self, name, args):
            self.names.append(name)
            return self.approve

    return Recorder()


# ===== 三种模式的分诊 =====

@pytest.mark.parametrize(
    "mode, tool_name, expect_ask",
    [
        ("confirm", "read_file", True),      # confirm 连只读也要问
        ("confirm", "write_file", True),
        ("smart", "read_file", False),       # smart 只读自动放行
        ("smart", "grep_files", False),
        ("smart", "write_file", True),       # 写操作仍需确认
        ("smart", "run_bash", True),
        ("auto", "read_file", False),        # auto 全放行
        ("auto", "run_bash", False),
    ],
)
def test_permission_mode_decides_confirmation(make_agent, stub_tools, asked, mode, tool_name, expect_ask):
    agent = make_agent([tool_call(tool_name, "{}"), "完成"], system_prompt=None, permission_mode=mode)

    agent.run("干活", confirm_tool=asked.confirm)

    assert (tool_name in asked.names) is expect_ask
    assert len(stub_tools.calls) == 1, "无论问不问，工具都只执行一次"


def test_missing_confirm_callback_falls_through_to_execution(make_agent, stub_tools):
    """没有 UI 回调时不能卡住：确认无从发起，直接执行。"""
    agent = make_agent([tool_call("run_bash", "{}"), "完成"], system_prompt=None, permission_mode="confirm")

    agent.run("跑命令", confirm_tool=None)

    assert stub_tools.calls == [("run_bash", {})]


def test_user_refusal_still_writes_paired_tool_result(make_agent, stub_tools, asked):
    asked.approve = False
    agent = make_agent(
        [tool_call("edit_file", '{"path": "a.txt"}', call_id="call_1"), "好的，我不改了"],
        system_prompt=None,
    )

    assert agent.run("改文件", confirm_tool=asked.confirm) == "好的，我不改了"

    assert stub_tools.calls == [], "被拒绝的工具绝不能执行"
    assert "用户拒绝执行: edit_file" in tool_results(agent)[0].content
    assert tool_results(agent)[0].tool_call_id == "call_1"
    assert_tool_pairs_complete(branch_messages(agent))


def test_partial_refusal_keeps_pairing_across_multiple_calls(make_agent, stub_tools):
    """一轮多个工具、只拒绝其中一个：两条结果都得存在且 id 对得上。"""
    turn = tool_call("read_file", '{"path": "a"}', call_id="call_a", index=0)
    turn.deltas += tool_call("run_bash", '{"command": "ls"}', call_id="call_b", index=1).deltas
    agent = make_agent([turn, "一个做了，一个没做"], system_prompt=None)

    def confirm(name, args):
        return name == "read_file"

    agent.run("读并执行", confirm_tool=confirm)

    assert stub_tools.calls == [("read_file", {"path": "a"})]
    contents = {m.tool_call_id: m.content for m in tool_results(agent)}
    assert contents["call_a"] == "[stub] read_file 已执行"
    assert contents["call_b"] == "用户拒绝执行: run_bash"
    assert_tool_pairs_complete(branch_messages(agent))


# ===== 模式设置 =====

@pytest.mark.parametrize("mode", ["confirm", "smart", "auto"])
def test_set_permission_mode_accepts_known_values(mode):
    agent = Agent(llm=object(), session_manager=object())
    assert agent.set_permission_mode(mode) == mode
    assert agent.permission_mode == mode


def test_set_permission_mode_ignores_invalid_value():
    agent = Agent(llm=object(), session_manager=object(), permission_mode="smart")

    assert agent.set_permission_mode("yolo") == "smart"
    assert agent.permission_mode == "smart"


def test_constructor_falls_back_to_confirm_on_invalid_mode():
    agent = Agent(llm=object(), session_manager=object(), permission_mode="YOLO")
    assert agent.permission_mode == "confirm"
