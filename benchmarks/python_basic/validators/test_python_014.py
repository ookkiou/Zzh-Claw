import pytest
from graph import dependency_order


def test_dependency():
    graph = {"a": ["z", "z"], "b": []}
    assert dependency_order(graph) == ["b", "z", "a"]
    assert graph == {"a": ["z", "z"], "b": []}


def test_diamond():
    assert dependency_order({"d": ["b", "c"], "b": ["a"], "c": ["a"]}) == [
        "a",
        "b",
        "c",
        "d",
    ]


def test_empty():
    assert dependency_order({}) == []


@pytest.mark.parametrize("graph", [{"a": ["a"]}, {"a": ["b"], "b": ["a"]}])
def test_cycle(graph):
    with pytest.raises(ValueError):
        dependency_order(graph)
