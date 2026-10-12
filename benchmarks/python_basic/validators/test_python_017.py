import json

import pytest
from storage import save_json


def test_save(tmp_path):
    path = tmp_path / "nested" / "data.json"
    save_json(path, {"名字": ["好", 1]})
    assert json.loads(path.read_text()) == {"名字": ["好", 1]}
    assert len(list(path.parent.iterdir())) == 1


def test_failure(tmp_path):
    path = tmp_path / "data.json"
    path.write_text("original")
    with pytest.raises(TypeError):
        save_json(path, {"bad": object()})
    assert path.read_text() == "original" and list(tmp_path.iterdir()) == [path]


def test_replace(tmp_path):
    path = tmp_path / "data.json"
    path.write_text("old")
    save_json(path, [1])
    assert json.loads(path.read_text()) == [1]
