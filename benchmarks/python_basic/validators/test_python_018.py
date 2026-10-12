from dataclasses import is_dataclass

import pytest
from inventory import reserve
from models import Product


def test_reserve():
    p = Product("x", 3)
    assert is_dataclass(p)
    assert reserve(p, 2) == 1 and reserve(p, 1) == 0 and p.stock == 0


@pytest.mark.parametrize("qty", [0, -1, True, 1.5, 4])
def test_no_change(qty):
    p = Product("x", 3)
    with pytest.raises(ValueError):
        reserve(p, qty)
    assert p.stock == 3


@pytest.mark.parametrize("stock", [-1, True, 1.5])
def test_invalid_stock(stock):
    with pytest.raises(ValueError):
        Product("x", stock)
