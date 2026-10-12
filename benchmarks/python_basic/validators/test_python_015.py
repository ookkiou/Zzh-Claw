import pytest
from paths import resolve_inside


def test_inside(tmp_path):
    assert resolve_inside(tmp_path, "a/../b") == tmp_path / "b"
    assert resolve_inside(tmp_path, "") == tmp_path


def test_outside(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    for path in ["../root-other/x", str(root / "x"), "../../x"]:
        with pytest.raises(ValueError):
            resolve_inside(root, path)


def test_symlink(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        resolve_inside(root, "link/file")
