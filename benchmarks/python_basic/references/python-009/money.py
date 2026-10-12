from decimal import ROUND_HALF_UP, Decimal


def total_amount(values):
    return sum((Decimal(v) for v in values), Decimal("0")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
