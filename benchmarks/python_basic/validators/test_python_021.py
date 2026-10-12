import pytest
from events import EventBus


def test_order():
    bus = EventBus()

    def a(x):
        return x + 1

    def b(x):
        return x + 2

    bus.on("e", a)
    bus.on("e", a)
    bus.on("e", b)
    assert bus.emit("e", 1) == [2, 3]
    assert EventBus().emit("e", 1) == []
    bus.off("missing", a)
    bus.off("e", a)
    bus.off("e", a)
    assert bus.emit("e", 1) == [3]


def test_snapshot():
    bus = EventBus()

    def b(x):
        return "b"

    def c(x):
        return "c"

    def a(x):
        bus.off("e", b)
        bus.on("e", c)
        return "a"

    bus.on("e", a)
    bus.on("e", b)
    assert bus.emit("e", 0) == ["a", "b"] and bus.emit("e", 0) == ["a", "c"]


def test_exception():
    bus = EventBus()

    def bad(x):
        raise ValueError("callback")

    bus.on("e", bad)
    with pytest.raises(ValueError):
        bus.emit("e", 0)
