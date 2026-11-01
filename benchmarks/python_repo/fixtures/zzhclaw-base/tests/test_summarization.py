"""历史摘要压缩（coding/session/manager.py:397-487）。

重点在边界对齐：压缩区不能把 assistant 和它的 tool 结果切开，否则截断视图会送出不配对的会话。
"""

import pytest
from zzhclaw.coding.session import SessionManager


@pytest.fixture
def sm(tmp_path):
    return SessionManager(storage_dir=str(tmp_path / "sessions"))


def fill(sm, count, prefix="m"):
    sm.create_session("摘要测试")
    for i in range(count):
        sm.add_message("user", f"{prefix}{i}")


def recorder(result="摘要"):
    """返回 (callable, calls)；callable 把每次收到的参数记下来。"""
    calls = []

    def fn(existing_summary, messages):
        calls.append({"existing": existing_summary, "messages": messages})
        return result

    return fn, calls


def run(sm, fn, keep_recent=1, min_new=10):
    return sm.summarize_old_messages(summarize_fn=fn, keep_recent=keep_recent,
                                     min_new_to_summarize=min_new)


# ===== 触发条件 =====

def test_no_session_returns_false(sm):
    fn, calls = recorder()
    assert run(sm, fn) is False
    assert calls == []


def test_empty_branch_returns_false(sm):
    fill(sm, 0)
    fn, calls = recorder()

    assert run(sm, fn) is False
    assert calls == []


def test_not_enough_old_messages_returns_false(sm):
    fill(sm, 5)
    fn, calls = recorder()

    assert run(sm, fn, keep_recent=5, min_new=1) is False
    assert calls == []


def test_below_min_new_threshold_returns_false(sm):
    """12 条消息、保留最近 1 条 → 待压缩 11 条；阈值 12 时不应触发。"""
    fill(sm, 12)
    fn, calls = recorder()

    assert run(sm, fn, keep_recent=1, min_new=12) is False
    assert calls == []


def test_leading_system_prompt_is_protected_from_compression(sm):
    sm.create_session()
    sm.add_message("system", "系统指令")
    for i in range(12):
        sm.add_message("user", f"m{i}")
    fn, calls = recorder()

    assert run(sm, fn) is True

    assert [m["content"] for m in calls[0]["messages"]][0] != "系统指令"
    assert sm.current_session.current_branch.summary_up_to_index == 12


# ===== 成功路径 =====

def test_success_updates_summary_and_persists(sm):
    fill(sm, 12)
    session = sm.current_session
    fn, calls = recorder(result="这段被压缩了")

    assert run(sm, fn) is True

    branch = session.current_branch
    assert branch.summary == "这段被压缩了"
    assert branch.summary_up_to_index == 11, "keep_recent=1 → 前 11 条进摘要，最后 1 条留原文"
    assert [m["content"] for m in calls[0]["messages"]] == [f"m{i}" for i in range(11)]

    reloaded = SessionManager(storage_dir=sm.storage_dir).load_session(session.id)
    assert reloaded.current_branch.summary == "这段被压缩了"


def test_summary_text_is_stripped(sm):
    fill(sm, 12)
    fn, _ = recorder(result="  带空白的摘要  \n")

    run(sm, fn)

    assert sm.current_session.current_branch.summary == "带空白的摘要"


def test_second_run_merges_into_existing_summary(sm):
    fill(sm, 12)
    fn, calls = recorder()
    run(sm, fn)
    assert calls[0]["existing"] is None

    for i in range(12):
        sm.add_message("user", f"n{i}")
    assert run(sm, fn) is True

    # 第一次压缩了 m0..m10，所以增量区从 m11 开始
    assert calls[1]["existing"] == "摘要"
    assert [m["content"] for m in calls[1]["messages"]] == ["m11"] + [f"n{i}" for i in range(11)]
    assert sm.current_session.current_branch.summary_up_to_index == 23


def test_summary_applies_only_to_current_branch(sm):
    fill(sm, 12)
    main = sm.current_session.current_branch
    sm.fork_branch(11, "分支")
    fn, _ = recorder()

    run(sm, fn)

    assert sm.current_session.current_branch.summary == "摘要"
    assert main.summary is None


# ===== 边界对齐 =====

def test_tool_results_follow_their_assistant_into_the_summary(sm):
    """边界落在 tool 消息上时后推，避免把结果留在原文区、assistant 却进了摘要。"""
    sm.create_session()
    for i in range(10):
        sm.add_message("user", f"m{i}")
    sm.add_message("assistant", "", tool_calls=[
        {"id": "call_a", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
    ])
    sm.add_message("tool", "结果", tool_call_id="call_a")
    fn, calls = recorder()

    assert run(sm, fn) is True

    assert sm.current_session.current_branch.summary_up_to_index == 12
    assert [m["role"] for m in calls[0]["messages"]][-2:] == ["assistant", "tool"]


def test_assistant_with_missing_result_is_left_out_of_the_summary(sm):
    """压缩区末尾是个结果尚未产生的 assistant：前移边界，留到下次一起压缩。"""
    sm.create_session()
    for i in range(10):
        sm.add_message("user", f"m{i}")
    sm.add_message("assistant", "", tool_calls=[
        {"id": "call_a", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
    ])
    sm.add_message("user", "m11（结果从未写入，模拟中断）")
    fn, calls = recorder()

    assert run(sm, fn) is True

    assert sm.current_session.current_branch.summary_up_to_index == 10
    assert len(calls[0]["messages"]) == 10


# ===== 降级路径 =====

def test_summarize_failure_leaves_state_untouched(sm):
    fill(sm, 12)
    branch = sm.current_session.current_branch

    def boom(existing, messages):
        raise RuntimeError("网络断了")

    assert run(sm, boom) is False
    assert (branch.summary, branch.summary_up_to_index) == (None, 0)


@pytest.mark.parametrize("bad", ["", None, 123, []])
def test_unusable_summary_result_is_rejected(sm, bad):
    fill(sm, 12)
    branch = sm.current_session.current_branch
    fn, _ = recorder(result=bad)

    assert run(sm, fn) is False
    assert (branch.summary, branch.summary_up_to_index) == (None, 0)


def test_agent_ignores_summarization_failures(make_agent, session_manager):
    """摘要异常不能打断对话：SessionManager 吞异常，Agent 外层还有一道 try。"""
    agent = make_agent(["正常回复"])
    session_manager.create_session()
    for i in range(35):  # 超过 keep_recent=20 且达到 min_new_to_summarize=10
        session_manager.add_message("user", f"m{i}")

    def boom(existing, messages):
        raise RuntimeError("摘要挂了")

    agent.llm.summarize = boom

    assert agent.run("你好") == "正常回复"
    assert agent.session_manager.current_session.current_branch.summary is None
