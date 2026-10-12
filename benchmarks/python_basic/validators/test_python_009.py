from decimal import Decimal

from money import total_amount


def test_precision():
    value = total_amount(iter(["0.1", "0.2"]))
    assert isinstance(value, Decimal) and value == Decimal("0.30")
    assert value.as_tuple().exponent == -2


def test_rounding():
    assert total_amount(["1.005"]) == Decimal("1.01")
    assert total_amount(["-1.005"]) == Decimal("-1.01")
    assert total_amount(["0.004", "0.004"]) == Decimal("0.01")


def test_empty():
    assert str(total_amount([])) == "0.00"
