import pytest
from bounds import clamp


@pytest.mark.parametrize(
    "v,lo,hi,want",
    [(-1, 0, 3, 0), (5, 0, 3, 3), (2, 0, 3, 2), (4, 4, 4, 4), (1.5, 0, 2, 1.5)],
)
def test_clamp(v, lo, hi, want):
    assert clamp(v, lo, hi) == want


def test_invalid():
    with pytest.raises(ValueError):
        clamp(0, 3, 1)
