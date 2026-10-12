import copy

import pytest
from workflow import plan, run


@pytest.mark.parametrize(
    "graph,expected",
    [
        ({}, []),
        ({"z": [], "a": ["z"], "b": []}, ["b", "z", "a"]),
        ({"c": ["b", "b"], "b": ["a"], "a": []}, ["a", "b", "c"]),
    ],
)
def test_plans(graph, expected):
    before = copy.deepcopy(graph)
    assert plan(graph) == expected
    assert graph == before


@pytest.mark.parametrize(
    "graph", [{"a": ["z"]}, {"a": ["a"]}, {"a": ["b"], "b": ["a"]}]
)
def test_invalid_no_side_effects(graph):
    calls = []
    with pytest.raises(ValueError):
        run(graph, {k: lambda: calls.append(1) for k in graph})
    assert calls == []


def test_missing_action_before_execution():
    calls = []
    with pytest.raises(ValueError):
        run({"a": [], "z": []}, {"a": lambda: calls.append("a")})
    assert calls == []


def test_branch_failures_and_reset():
    calls = []

    def fail():
        calls.append("a")
        raise RuntimeError("boom")

    graph = {"a": [], "b": ["a"], "c": ["b"], "d": []}
    actions = {key: (lambda key=key: calls.append(key)) for key in graph}
    actions["a"] = fail
    assert run(graph, actions) == {
        "a": "failed",
        "b": "skipped",
        "c": "skipped",
        "d": "passed",
    }
    assert calls == ["a", "d"]
    actions["a"] = lambda: None
    assert set(run(graph, actions).values()) == {"passed"}
