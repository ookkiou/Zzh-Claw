from sequences import unique


def test_order():
    assert unique([3, 1, 3, 2, 1]) == [3, 1, 2]


def test_unhashable():
    items = [[1], {"a": 1}, [1], {"a": 1}, [2]]
    assert unique(items) == [[1], {"a": 1}, [2]]
    assert len(items) == 5


def test_iterator():
    assert unique(iter([2, 2, 1])) == [2, 1]


def test_empty():
    assert unique([]) == []
