import pytest
from calculator import divide


@pytest.mark.parametrize(
    "a,b,expected", [(8, 2, 4), (-3, 2, -1.5), (0, 5, 0), (1, 0.5, 2)]
)
def test_regular(a, b, expected):
    assert divide(a, b) == expected


@pytest.mark.parametrize("zero", [0, 0.0, -0.0])
def test_zero(zero):
    with pytest.raises(ValueError):
        divide(1, zero)
