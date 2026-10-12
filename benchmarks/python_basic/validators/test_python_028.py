import pytest
from rle import decode, encode


def test_roundtrip():
    for text in ["", "aaabbcaa", "好好🙂🙂x", "a\n\n"]:
        assert decode(iter(encode(text))) == text
    assert encode("aaabbcaa") == [("a", 3), ("b", 2), ("c", 1), ("a", 2)]


@pytest.mark.parametrize(
    "runs",
    [[("", 1)], [("ab", 2)], [("a", 0)], [("a", -1)], [("a", True)], [("a", 1.2)]],
)
def test_invalid(runs):
    with pytest.raises(ValueError):
        decode(runs)
