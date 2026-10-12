from decimal import Decimal

import pytest
from ledger import Ledger


@pytest.mark.parametrize(
    "bad", [True, False, "0", "-1", "0.001", "NaN", "Infinity", "oops", None]
)
def test_invalid_atomic(bad):
    original = {"a": Decimal("10"), "b": Decimal("0")}
    obj = Ledger(original)
    with pytest.raises(ValueError):
        obj.transfer("k", "a", "b", bad)
    assert obj.balances == original
    obj.transfer("k", "a", "b", "1.20")
    assert obj.balances == {"a": Decimal("8.80"), "b": Decimal("1.20")}
    assert original == {"a": Decimal("10"), "b": Decimal("0")}


def test_retries_and_receipt_ownership():
    obj = Ledger({"a": Decimal("10"), "b": Decimal("0")})
    first = obj.transfer("x", "a", "b", "1.230")
    first["amount"] = 999
    assert obj.transfer("x", "a", "b", Decimal("1.23"))["amount"] == Decimal("1.23")
    assert obj.balances["a"] == Decimal("8.77")
    with pytest.raises(ValueError):
        obj.transfer("x", "a", "b", "2")
    assert obj.balances["a"] == Decimal("8.77")


@pytest.mark.parametrize(
    "src,dst,value",
    [("a", "a", "1"), ("a", "z", "1"), ("z", "b", "1"), ("a", "b", "20")],
)
def test_failure_does_not_reserve(src, dst, value):
    obj = Ledger({"a": Decimal("10"), "b": Decimal("0")})
    with pytest.raises(ValueError):
        obj.transfer("x", src, dst, value)
    assert obj.balances == {"a": Decimal("10"), "b": Decimal("0")}
    obj.transfer("x", "a", "b", "10")
    assert obj.balances["a"] == 0
