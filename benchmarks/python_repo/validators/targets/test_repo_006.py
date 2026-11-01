import pytest

from zzhclaw.coding.session import SessionManager


@pytest.mark.parametrize(
    "coverage,fork_index,keep",
    [
        (4, 1, False),
        (3, 1, False),
        (2, 1, True),
        (1, 0, True),
        (3, 3, True),
        (0, 1, False),
    ],
)
def test_summary_does_not_cross_fork_point(tmp_path, coverage, fork_index, keep):
    sm = SessionManager(str(tmp_path / "sessions"))
    sm.create_session("history")
    for i in range(4):
        sm.add_message("user", f"message {i}")
    parent = sm.current_session.current_branch
    parent.summary = "contains covered facts"
    parent.summary_up_to_index = coverage
    child = sm.fork_branch(fork_index, "child")
    assert child.summary == ("contains covered facts" if keep else None)
    assert child.summary_up_to_index == (coverage if keep else 0)
    assert (
        parent.summary == "contains covered facts"
        and parent.summary_up_to_index == coverage
    )
    exposed = " ".join(m.get("content") or "" for m in sm.get_messages())
    if not keep:
        assert "contains covered facts" not in exposed


def test_explicit_reset_keeps_existing_behavior(tmp_path):
    sm = SessionManager(str(tmp_path / "sessions"))
    sm.create_session()
    sm.add_message("user", "hello")
    parent = sm.current_session.current_branch
    parent.summary = "hello"
    parent.summary_up_to_index = 1
    child = sm.fork_branch(0, "child", reset_summary=True)
    assert child.summary is None and child.summary_up_to_index == 0
