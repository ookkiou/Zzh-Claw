"""上下文窗口装配与截断（coding/session/manager.py:289-395）。

发给 LLM 的消息必须同时满足：不超预算、且 function calling 配对完整。
这两条会互相拉扯，所以截断后还要做孤儿清理和缺失补位。
"""

import json

import pytest


def tc(call_id, name="read_file", arguments='{"path": "a"}'):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


@pytest.fixture
def sm(tmp_path):
    from zzhclaw.coding.session import SessionManager

    return SessionManager(storage_dir=str(tmp_path / "sessions"))


def start(sm, *specs):
    """specs: (role, content[, add_message kwargs])。"""
    sm.create_session("窗口测试")
    for spec in specs:
        kwargs = spec[2] if len(spec) > 2 else {}
        sm.add_message(spec[0], spec[1], **kwargs)
    return sm.current_session.current_branch


# ===== 基础转换 =====

def test_no_session_returns_empty(sm):
    assert sm.get_messages() == []


def test_empty_branch_returns_empty(sm):
    start(sm)
    assert sm.get_messages() == []


def test_messages_are_converted_to_openai_shape(sm):
    start(sm, ("user", "问题"), ("assistant", "", {"tool_calls": [tc("call_1")]}),
          ("tool", "结果", {"tool_call_id": "call_1"}))

    assert sm.get_messages() == [
        {"role": "user", "content": "问题"},
        {"role": "assistant", "content": "", "tool_calls": [tc("call_1")]},
        {"role": "tool", "content": "结果", "tool_call_id": "call_1"},
    ]


def test_get_messages_does_not_mutate_stored_history(sm):
    branch = start(sm, *[("user", f"m{i}") for i in range(30)])

    sm.get_messages(max_messages=3)

    assert len(branch.messages) == 30


# ===== 滑动窗口与字符预算 =====

def test_window_keeps_most_recent_messages(sm):
    start(sm, *[("user", f"m{i}") for i in range(10)])

    assert [m["content"] for m in sm.get_messages(max_messages=3)] == ["m7", "m8", "m9"]


def test_leading_system_stays_outside_the_window(sm):
    start(sm, ("system", "系统指令"), *[("user", f"m{i}") for i in range(10)])

    msgs = sm.get_messages(max_messages=2)

    assert msgs[0] == {"role": "system", "content": "系统指令"}
    assert [m["content"] for m in msgs[1:]] == ["m8", "m9"]


def test_only_the_first_system_message_is_hoisted(sm):
    """历史里中途出现的 system 消息按普通消息处理，不享受保留待遇。"""
    start(sm, ("system", "指令"), ("user", "1"), ("system", "中途插话"), ("user", "2"))

    msgs = sm.get_messages(max_messages=2)

    assert [m["content"] for m in msgs] == ["指令", "中途插话", "2"]


def test_char_budget_drops_oldest_first(sm):
    start(sm, ("user", "x" * 10), ("assistant", "y" * 10), ("user", "z" * 10))

    assert [m["content"] for m in sm.get_messages(max_chars=25)] == ["y" * 10, "z" * 10]


def test_char_budget_never_empties_the_window(sm):
    """预算再紧也至少留一条原文，否则模型拿到空上下文。"""
    start(sm, ("user", "x" * 10), ("assistant", "y" * 10), ("user", "z" * 10))

    assert len(sm.get_messages(max_chars=1)) == 1


def test_tool_call_arguments_count_against_the_budget(sm):
    """工具参数（write_file 的整篇 content）必须计入预算。

    超预算的 assistant 被砍掉后，它的 tool 结果变孤儿，也一并被清掉。
    """
    big_args = json.dumps({"path": "a.txt", "content": "c" * 400})
    start(sm, ("user", "写文件"),
          ("assistant", "", {"tool_calls": [tc("call_1", "write_file", big_args)]}),
          ("tool", "成功写入", {"tool_call_id": "call_1"}),
          ("user", "写好了"))

    msgs = sm.get_messages(max_chars=100)

    assert msgs == [{"role": "user", "content": "写好了"}]


# ===== 摘要注入 =====

def test_summary_becomes_second_system_message(sm):
    branch = start(sm, ("system", "系统指令"), ("user", "1"), ("assistant", "2"),
                   ("user", "3"), ("assistant", "4"))
    branch.summary = "用户询问了 1，助手回答了 2"
    branch.summary_up_to_index = 3

    msgs = sm.get_messages()

    assert msgs[0] == {"role": "system", "content": "系统指令"}
    assert msgs[1]["content"] == "[历史对话摘要]\n用户询问了 1，助手回答了 2"
    assert [m["content"] for m in msgs[2:]] == ["3", "4"], \
        "summary_up_to_index=3 覆盖前 3 条（含 system），第 4 条起才是原文"


def test_summary_without_leading_system(sm):
    branch = start(sm, ("user", "1"), ("assistant", "2"), ("user", "3"))
    branch.summary = "前情"
    branch.summary_up_to_index = 2

    msgs = sm.get_messages()

    assert [m["role"] for m in msgs] == ["system", "user"]
    assert msgs[1]["content"] == "3"


def test_summary_survives_a_tight_budget(sm):
    branch = start(sm, ("user", "u" * 50), ("assistant", "a" * 50))
    branch.summary = "s" * 40
    branch.summary_up_to_index = 1

    msgs = sm.get_messages(max_chars=60)

    assert [m["role"] for m in msgs] == ["system", "assistant"]
    assert msgs[0]["content"] == "[历史对话摘要]\n" + "s" * 40


# ===== 配对自愈 =====

def test_orphan_tool_at_window_head_is_dropped(sm):
    start(sm, ("assistant", "", {"tool_calls": [tc("call_a")]}),
          ("tool", "结果 A", {"tool_call_id": "call_a"}),
          ("assistant", "", {"tool_calls": [tc("call_b")]}),
          ("tool", "结果 B", {"tool_call_id": "call_b"}),
          ("user", "收尾"))

    assert sm.get_messages(max_messages=2) == [{"role": "user", "content": "收尾"}]


def test_incomplete_assistant_at_head_is_dropped_recursively(sm):
    """窗口开头是个没结果的 assistant：先砍它，再砍它露出来的孤立 tool。"""
    start(sm, ("assistant", "", {"tool_calls": [tc("call_a")]}),
          ("tool", "结果 A", {"tool_call_id": "call_a"}),
          ("assistant", "", {"tool_calls": [tc("call_b")]}))

    assert sm.get_messages(max_messages=2) == []


def test_missing_tool_result_is_backfilled(sm):
    branch = start(sm, ("user", "问题"),
                   ("assistant", "", {"tool_calls": [tc("call_a")]}),
                   ("tool", "结果", {"tool_call_id": "call_a"}))
    branch.messages.pop()  # 模拟 tool 结果因异常从未写入

    msgs = sm.get_messages()

    assert [m["role"] for m in msgs] == ["user", "assistant", "tool"]
    assert msgs[2] == {"role": "tool", "content": "[工具未执行]", "tool_call_id": "call_a"}


def test_every_unanswered_tool_call_is_backfilled(sm):
    start(sm, ("user", "执行"),
          ("assistant", "", {"tool_calls": [tc("call_a"), tc("call_b", "run_bash")]}))

    msgs = sm.get_messages()

    assert [m.get("tool_call_id") for m in msgs if m["role"] == "tool"] == ["call_a", "call_b"]
    assert all(m["content"] == "[工具未执行]" for m in msgs if m["role"] == "tool")


def test_backfill_only_fills_the_gaps(sm):
    """补位按 tool_calls 逐个检查，已有真实结果的不重复补。

    顺带钉住一个次优行为：占位消息被插在其 assistant 之后、真实结果之前，
    因此 tool 结果的顺序与 tool_calls 顺序不一致（配对完整，多数实现可接受）。
    """
    start(sm, ("user", "执行"),
          ("assistant", "", {"tool_calls": [tc("call_a"), tc("call_b")]}),
          ("tool", "A 的真实结果", {"tool_call_id": "call_a"}))

    msgs = sm.get_messages()

    assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "tool"]
    assert [m["tool_call_id"] for m in msgs[2:]] == ["call_b", "call_a"]
    assert msgs[2]["content"] == "[工具未执行]"
    assert msgs[3]["content"] == "A 的真实结果"


def test_backfill_runs_after_head_trimming_not_before(sm):
    """补位只救非开头的位置：开头的未配对 assistant 会被整条砍掉。"""
    start(sm, ("assistant", "", {"tool_calls": [tc("call_a")]}), ("user", "后续"))

    assert sm.get_messages(max_messages=2) == [{"role": "user", "content": "后续"}]
