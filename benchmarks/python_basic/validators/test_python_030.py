import cache_api
import pytest
from cache_core import LRUCache


def test_public():
    assert cache_api.LRUCache is LRUCache


def test_eviction():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") == 1
    c.put("c", 3)
    assert c.get("b", "missing") == "missing" and c.get("c") == 3
    c.put("a", 4)
    c.put("d", 5)
    assert c.get("c") is None and c.get("a") == 4


def test_falsy_and_independent():
    c = LRUCache(2)
    c.put("a", None)
    c.put("b", False)
    assert (
        c.get("a", "x") is None
        and c.get("b", "x") is False
        and LRUCache(2).get("a", "x") == "x"
    )


@pytest.mark.parametrize("capacity", [0, -1, True, 1.2])
def test_invalid(capacity):
    with pytest.raises(ValueError):
        LRUCache(capacity)
