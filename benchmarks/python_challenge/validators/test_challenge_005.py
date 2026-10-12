import random

import pytest
from framekit import Decoder, FrameError, encode


@pytest.mark.parametrize("seed", range(12))
def test_arbitrary_splits(seed):
    rng = random.Random(seed)
    payloads = [b"", bytes(range(256)), b"hello", b"\xff\x00", b""]
    wire = b"".join(len(p).to_bytes(4, "big") + p for p in payloads)
    d = Decoder(256)
    output = []
    offset = 0
    while offset < len(wire):
        size = rng.randint(1, 13)
        output.extend(d.feed(wire[offset : offset + size]))
        offset += size
    assert output == payloads
    assert d.finish() is None
    with pytest.raises(FrameError):
        d.feed(b"")
    d.reset()
    assert d.feed(encode(b"x")) == [b"x"]


@pytest.mark.parametrize("value", [True, -1, 1.5, "2", None])
def test_limits(value):
    with pytest.raises(ValueError):
        Decoder(value)


def test_oversize_immediate_and_reset():
    d = Decoder(2)
    with pytest.raises(FrameError):
        d.feed((3).to_bytes(4, "big"))
    with pytest.raises(FrameError):
        d.feed(b"")
    with pytest.raises(FrameError):
        d.finish()
    d.reset()
    assert d.feed(encode(b"ab")) == [b"ab"]
    with pytest.raises(FrameError):
        d.feed(encode(b"abc"))


@pytest.mark.parametrize("wire", [b"\x00", b"\x00\x00\x00\x02x"])
def test_truncation(wire):
    d = Decoder()
    assert d.feed(wire) == []
    with pytest.raises(FrameError):
        d.finish()
    d.reset()
    assert d.feed(encode(b"")) == [b""]


def test_types_and_zero():
    d = Decoder(0)
    assert d.feed(b"\x00\x00") == []
    with pytest.raises(TypeError):
        d.feed("xx")
    assert d.feed(b"\x00\x00") == [b""]
    for value in ["a", bytearray(b"a"), None]:
        with pytest.raises(TypeError):
            encode(value)
    assert encode(b"ab") == b"\x00\x00\x00\x02ab"
