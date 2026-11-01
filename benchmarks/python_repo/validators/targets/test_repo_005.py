from zzhclaw.coding.session import SessionManager


def prepare(tmp_path):
    sm = SessionManager(str(tmp_path / "sessions"))
    sm.create_session("history")
    sm.add_message("user", "question")
    sm.add_message(
        "assistant",
        "answer",
        tool_calls=[
            {
                "id": "call_a",
                "type": "function",
                "function": {"name": "read_file", "arguments": "{}"},
                "extra": {"labels": ["original"]},
            }
        ],
    )
    return sm, sm.current_session.current_branch


def test_nested_message_mutation_is_branch_local(tmp_path):
    sm, parent = prepare(tmp_path)
    original_id = parent.messages[1].id
    stamp = parent.messages[1].timestamp
    child = sm.fork_branch(1, "child")
    child.messages[0].content = "child question"
    child.messages[1].tool_calls[0]["extra"]["labels"].append("child")
    assert parent.messages[0].content == "question"
    assert parent.messages[1].tool_calls[0]["extra"]["labels"] == ["original"]
    assert child.messages[1].id == original_id and child.messages[1].timestamp == stamp
    assert child.parent_message_id == original_id
    sm.save_session()
    sm.load_session(sm.current_session.id)
    assert sm.current_session.branches["main"].messages[0].content == "question"
    assert sm.current_session.branches[child.id].messages[0].content == "child question"


def test_siblings_and_parent_changes_are_independent(tmp_path):
    sm, parent = prepare(tmp_path)
    a = sm.fork_branch(1, "a")
    sm.switch_branch("main")
    b = sm.fork_branch(1, "b")
    parent.messages[1].tool_calls[0]["function"]["name"] = "changed"
    a.messages[1].tool_calls[0]["extra"]["labels"].clear()
    assert b.messages[1].tool_calls[0]["function"]["name"] == "read_file"
    assert b.messages[1].tool_calls[0]["extra"]["labels"] == ["original"]
