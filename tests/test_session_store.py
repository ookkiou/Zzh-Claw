"""会话存取与分支（coding/session/manager.py）。"""

import json

import pytest
from zzhclaw.coding.session import Message, Session, SessionBranch, SessionManager


@pytest.fixture
def sm(tmp_path):
    return SessionManager(storage_dir=str(tmp_path / "sessions"))


def new_session(sm, *turns):
    sm.create_session("测试会话")
    for role, content in turns:
        sm.add_message(role, content)
    return sm.current_session


# ===== 创建与结构 =====

def test_create_session_starts_with_main_branch(sm):
    session = sm.create_session()

    assert len(session.id) == 8
    assert session.current_branch_id == "main"
    assert session.current_branch.name == "主线"
    assert session.current_branch.messages == []
    assert session.current_branch.summary is None


def test_generated_name_is_used_when_not_given(sm):
    assert sm.create_session().name.startswith("会话 ")


# ===== 序列化往返 =====

def test_session_round_trips_through_dict(sm):
    session = new_session(sm, ("system", "指令"), ("user", "你好"), ("assistant", "嗨"))
    sm.fork_branch(2, "分支")
    session.current_branch.summary = "前情提要"
    session.current_branch.summary_up_to_index = 1

    restored = Session.from_dict(json.loads(json.dumps(session.to_dict(), ensure_ascii=False)))

    assert restored == session


def test_message_round_trips_with_tool_fields():
    msg = Message(
        role="assistant",
        content="",
        timestamp="2026-01-01T00:00:00",
        id="abc12345",
        tool_calls=[{"id": "call_1", "type": "function",
                     "function": {"name": "read_file", "arguments": "{}"}}],
    )

    assert Message.from_dict(msg.to_dict()) == msg


def test_old_session_file_without_summary_fields_still_loads(sm):
    """摘要字段是后加的；旧磁盘文件必须能按默认值加载。"""
    legacy = {
        "id": "abcd1234",
        "name": "旧会话",
        "created_at": "2025-01-01T00:00:00",
        "current_branch_id": "main",
        "branches": {
            "main": {
                "id": "main",
                "name": "主线",
                "parent_message_id": None,
                "created_at": "2025-01-01T00:00:00",
                "messages": [],
            }
        },
    }

    branch = SessionBranch.from_dict(legacy["branches"]["main"])

    assert branch.summary is None
    assert branch.summary_up_to_index == 0


# ===== 落盘 =====

def test_atomic_save_leaves_only_the_session_file(sm, tmp_path):
    session = new_session(sm, ("user", "hi"))
    sm.save_session()

    entries = sorted(p.name for p in (tmp_path / "sessions").iterdir())
    assert entries == [f"{session.id}.json"], "临时文件不应残留"


def test_load_session_restores_messages(sm):
    session = new_session(sm, ("user", "一"), ("assistant", "二"))
    sm.save_session()

    loaded = SessionManager(storage_dir=sm.storage_dir).load_session(session.id)

    assert [m.content for m in loaded.current_branch.messages] == ["一", "二"]
    assert loaded == session


def test_load_missing_session_returns_none(sm):
    assert sm.load_session("nope1234") is None


def test_delete_session_removes_file_and_current_state(sm):
    session = new_session(sm, ("user", "hi"))

    assert sm.delete_session(session.id) is True
    assert sm.current_session is None
    assert sm.delete_session(session.id) is False


def test_list_sessions_counts_branches_and_messages(sm):
    session = new_session(sm, ("user", "a"), ("assistant", "b"))
    sm.fork_branch(1, "分支")
    sm.save_session(session)

    listed = sm.list_sessions()

    assert listed == [
        {
            "id": session.id,
            "name": "测试会话",
            "created_at": session.created_at,
            "branches": 2,
            "messages": 4,  # 分支复制了前 2 条
        }
    ]


def test_list_sessions_sorts_newest_first(sm):
    s1 = sm.create_session("旧")
    sm.add_message("user", "1")
    s1.created_at = "2026-01-01T00:00:00"
    sm.save_session(s1)

    s2 = sm.create_session("新")
    sm.add_message("user", "2")
    s2.created_at = "2026-06-01T00:00:00"
    sm.save_session(s2)

    listed = sm.list_sessions()

    assert [s["name"] for s in listed] == ["新", "旧"]


def test_list_sessions_survives_corrupt_file(sm, tmp_path):
    new_session(sm, ("user", "好会话"))
    (tmp_path / "sessions" / "badbad01.json").write_text("{not json", encoding="utf-8")

    listed = sm.list_sessions()

    assert len(listed) == 1, "损坏文件应被跳过而不是让整个列表崩掉"


def test_save_without_session_is_noop(sm):
    sm.save_session()
    assert sm.list_sessions() == []


# ===== 分支 =====

def test_fork_copies_prefix_and_switches_current(sm):
    new_session(sm, ("user", "1"), ("assistant", "2"), ("user", "3"), ("assistant", "4"))

    branch = sm.fork_branch(1, "从第 2 条分叉")

    assert [m.content for m in branch.messages] == ["1", "2"]
    assert branch.parent_message_id == branch.messages[-1].id
    assert sm.current_session.current_branch_id == branch.id
    assert sm.current_session.current_branch is branch


def test_fork_appending_does_not_touch_parent(sm):
    new_session(sm, ("user", "1"), ("assistant", "2"))
    main = sm.current_session.current_branch

    sm.fork_branch(1, "分支")
    sm.add_message("user", "3")

    assert [m.content for m in main.messages] == ["1", "2"]


def test_fork_inherits_summary_clamped_to_fork_point(sm):
    new_session(sm, ("user", "1"), ("assistant", "2"), ("user", "3"), ("assistant", "4"))
    branch = sm.current_session.current_branch
    branch.summary = "前三条的摘要"
    branch.summary_up_to_index = 3

    forked = sm.fork_branch(1, "分支")

    assert forked.summary == "前三条的摘要"
    assert forked.summary_up_to_index == 2, "摘要覆盖范围不能超过分叉点"


def test_fork_drops_summary_when_clamp_reaches_zero(sm):
    new_session(sm, ("user", "1"), ("assistant", "2"))
    branch = sm.current_session.current_branch
    branch.summary = "有摘要但没有覆盖任何消息"
    branch.summary_up_to_index = 0

    forked = sm.fork_branch(0, "分支")

    assert forked.summary is None
    assert forked.summary_up_to_index == 0


def test_fork_with_reset_summary_discards_summary(sm):
    new_session(sm, ("user", "1"), ("assistant", "2"))
    branch = sm.current_session.current_branch
    branch.summary = "旧摘要"
    branch.summary_up_to_index = 2

    forked = sm.fork_branch(1, "分支", reset_summary=True)

    assert (forked.summary, forked.summary_up_to_index) == (None, 0)


@pytest.mark.parametrize("index", [-1, 2, 99])
def test_fork_rejects_out_of_range_index(sm, index):
    new_session(sm, ("user", "1"), ("assistant", "2"))

    with pytest.raises(ValueError, match="无效的消息索引"):
        sm.fork_branch(index, "分支")


def test_fork_without_session_raises(sm):
    with pytest.raises(ValueError, match="没有活动会话"):
        sm.fork_branch(0, "分支")


def test_switch_branch_validates_id(sm):
    new_session(sm, ("user", "1"))
    forked = sm.fork_branch(0, "分支")

    sm.switch_branch("main")
    assert sm.current_session.current_branch_id == "main"
    sm.switch_branch(forked.id)
    assert sm.current_session.current_branch_id == forked.id

    with pytest.raises(ValueError, match="无效的分支 ID"):
        sm.switch_branch("ghost")


def test_switch_branch_without_session_raises(sm):
    with pytest.raises(ValueError, match="没有活动会话"):
        sm.switch_branch("main")


# ===== add_message =====

def test_add_message_without_session_is_dropped(sm):
    sm.add_message("user", "没人接收")
    assert sm.current_session is None
    assert sm.list_sessions() == []


def test_each_message_is_persisted_immediately(sm):
    session = new_session(sm, ("user", "1"))

    sm.add_message("assistant", "2")
    reloaded = SessionManager(storage_dir=sm.storage_dir).load_session(session.id)

    assert [m.content for m in reloaded.current_branch.messages] == ["1", "2"]
