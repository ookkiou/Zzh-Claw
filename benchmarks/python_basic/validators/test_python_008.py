import pytest
from cache import TTLCache


def test_expiry_and_refresh():
    now = [0]
    cache = TTLCache(3, lambda: now[0])
    cache.set("a", 7)
    now[0] = 2
    assert cache.get("a") == 7
    cache.set("a", 8)
    now[0] = 3
    assert cache.get("a") == 8
    now[0] = 5
    assert cache.get("a", "missing") == "missing"
    now[0] = 0
    assert cache.get("a") is None


def test_falsy():
    cache = TTLCache(2, lambda: 0)
    cache.set("a", None)
    cache.set("b", False)
    assert cache.get("a", "x") is None and cache.get("b", "x") is False
    assert cache.get("unknown", "x") == "x"


@pytest.mark.parametrize("ttl", [0, -1])
def test_invalid(ttl):
    with pytest.raises(ValueError):
        TTLCache(ttl, lambda: 0)
