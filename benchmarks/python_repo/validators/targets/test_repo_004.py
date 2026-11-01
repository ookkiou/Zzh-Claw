import json
from pathlib import Path

import pytest

from zzhclaw.coding.session import SessionManager


@pytest.mark.parametrize(
    "bad", ["../outside", "..", "a/b", "a\\b", "", "a.json", "中文", "/tmp/outside"]
)
def test_invalid_ids_do_not_mutate_state(tmp_path, bad):
    bad = str(tmp_path / "outside-absolute") if bad == "/tmp/outside" else bad
    sm = SessionManager(str(tmp_path / "store"))
    current = sm.create_session("current")
    sm.save_session()
    assert sm.load_session(bad) is None
    assert sm.delete_session(bad) is False
    assert sm.current_session is current
    current.id = bad
    with pytest.raises(ValueError):
        sm.save_session()


def test_traversal_and_symlink_leave_external_json_untouched(tmp_path):
    sm = SessionManager(str(tmp_path / "store"))
    current = sm.create_session("current")
    sm.save_session()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(current.to_dict()))
    original = outside.read_bytes()
    assert sm.load_session("../outside") is None
    assert not sm.delete_session("../outside")
    assert outside.read_bytes() == original
    link = Path(sm.storage_dir) / "linked.json"
    link.symlink_to(outside)
    assert sm.load_session("linked") is None
    assert not sm.delete_session("linked")
    assert link.is_symlink() and outside.read_bytes() == original
    current.id = "linked"
    with pytest.raises(ValueError):
        sm.save_session()
    assert outside.read_bytes() == original


def test_custom_legal_id_and_missing_session(tmp_path):
    sm = SessionManager(str(tmp_path / "store"))
    session = sm.create_session("legacy")
    session.id = "Legacy_123-name"
    sm.save_session()
    assert sm.load_session(session.id).name == "legacy"
    assert sm.load_session("missing") is None
    assert sm.delete_session(session.id) and sm.current_session is None
