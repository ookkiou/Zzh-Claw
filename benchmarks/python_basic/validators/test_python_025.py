from collector import collect


def test_independent():
    assert collect(1) == [1] and collect(2) == [2] and collect(3, None) == [3]


def test_supplied():
    bucket = []
    assert collect(1, bucket) is bucket and collect(2, bucket) == [1, 2]


def test_defaults():
    assert collect.__defaults__ == (None,)
