from decimal import Decimal, InvalidOperation


def amount(value):
    if isinstance(value, bool):
        raise ValueError("invalid amount")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("invalid amount") from None
    if (
        not result.is_finite()
        or result <= 0
        or result != result.quantize(Decimal("0.01"))
    ):
        raise ValueError("invalid amount")
    return result
