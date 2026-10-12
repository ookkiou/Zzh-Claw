from decimal import Decimal


def subtotal(lines):
    result = Decimal("0")
    for price, qty in lines:
        value = Decimal(price)
        if value < 0 or isinstance(qty, bool) or not isinstance(qty, int) or qty < 0:
            raise ValueError("invalid line")
        result += value * qty
    return result
