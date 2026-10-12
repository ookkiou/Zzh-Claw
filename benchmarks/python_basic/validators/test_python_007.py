from config import deep_merge


def test_nested():
    assert deep_merge({"a": {"x": 1, "y": 2}}, {"a": {"x": 3}}) == {
        "a": {"x": 3, "y": 2}
    }


def test_replacement():
    assert deep_merge({"a": [1], "b": {}}, {"a": [2], "b": None}) == {
        "a": [2],
        "b": None,
    }


def test_independent():
    a, b = {"x": [1]}, {"y": {"z": []}}
    result = deep_merge(a, b)
    result["x"].append(2)
    result["y"]["z"].append(3)
    assert a == {"x": [1]} and b == {"y": {"z": []}}


def test_empty():
    assert deep_merge({}, {}) == {}
