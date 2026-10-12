from decimal import Decimal

import pytest
from cart import checkout
from pricing import subtotal


def test_total():
    value = checkout(iter([("0.1", 3), ("1.005", 1)]), "0.1")
    assert isinstance(value, Decimal) and value == Decimal("1.44")
    assert checkout([("0.004", 2)]) == Decimal("0.01")
    assert str(checkout([])) == "0.00"
    assert isinstance(subtotal([]), Decimal)


@pytest.mark.parametrize(
    "lines", [[("-1", 1)], [("1", -1)], [("1", True)], [("1", 1.5)]]
)
def test_invalid(lines):
    with pytest.raises(ValueError):
        checkout(lines)


def test_tax():
    with pytest.raises(ValueError):
        checkout([], "-0.1")
