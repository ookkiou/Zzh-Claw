import pytest
from ranking import top_k


def test_stability():
    values = [("a", 2), ("b", 3), ("c", 3), ("d", 1)]
    assert top_k(iter(values), 2, lambda x: x[1]) == [("b", 3), ("c", 3)]
    assert values[0] == ("a", 2)


def test_edges():
    assert top_k([1, 3, 2], 5, lambda x: x) == [3, 2, 1]
    assert top_k([1], 0, lambda x: x) == [] and top_k([], 2, lambda x: x) == []


@pytest.mark.parametrize("k", [-1, True, "1", 1.5])
def test_invalid(k):
    with pytest.raises(ValueError):
        top_k([], k, lambda x: x)
