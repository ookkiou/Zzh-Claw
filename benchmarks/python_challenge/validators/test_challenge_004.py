import random

import pytest
from depcache import DependencyCache


def test_transitive_invalidation_and_replace():
    c = DependencyCache()
    c.set("a", 1)
    c.set("b", 2, ["a"])
    c.set("c", 3, ["b"])
    c.set("d", 4, ["a"])
    c.set("x", 9)
    c.set("b", 20, ["a"])
    with pytest.raises(KeyError):
        c.get("c")
    assert c.get("b") == 20 and c.get("d") == 4
    assert c.invalidate("a") == {"a", "b", "d"}
    assert c.get("x") == 9 and c.invalidate("absent") == set()


@pytest.mark.parametrize("deps", [["a"], ["b"], ["missing"]])
def test_invalid_set_is_atomic(deps):
    c = DependencyCache()
    c.set("a", 1)
    c.set("b", 2, ["a"])
    with pytest.raises(ValueError):
        c.set("a", 9, deps)
    assert c.get("a") == 1 and c.get("b") == 2


def test_copies():
    c = DependencyCache()
    v = {"x": [1]}
    c.set("a", v)
    v["x"].append(2)
    result = c.get("a")
    result["x"].append(3)
    assert c.get("a") == {"x": [1]}
    deps = ["a"]
    c.set("b", 2, deps)
    deps.clear()
    assert c.invalidate("a") == {"a", "b"}
    with pytest.raises(KeyError):
        DependencyCache().get("a")


@pytest.mark.parametrize("seed", range(8))
def test_generated_dag(seed):
    rng = random.Random(seed)
    c = DependencyCache()
    graph = {}
    for i in range(15):
        key = str(i)
        deps = {str(j) for j in range(i) if rng.random() < 0.18}
        graph[key] = deps
        c.set(key, i, deps)
    removed = {"0"}
    while True:
        new = removed | {k for k, d in graph.items() if d & removed}
        if new == removed:
            break
        removed = new
    assert c.invalidate("0") == removed
    for key in graph.keys() - removed:
        assert c.get(key) == int(key)
