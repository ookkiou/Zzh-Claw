import pytest
from sequences import chunked


def test_chunks():
    assert chunked(iter(range(5)), 2) == [[0, 1], [2, 3], [4]]


def test_edges():
    assert chunked([], 3) == []
    assert chunked([1, 2], 5) == [[1, 2]]
    assert chunked([1, 2], 1) == [[1], [2]]


@pytest.mark.parametrize("size", [0, -1, True, 1.2, "2"])
def test_invalid(size):
    with pytest.raises(ValueError):
        chunked([], size)
