from decimal import ROUND_HALF_UP, Decimal

from pricing import subtotal


def checkout(lines, tax_rate="0"):
    tax = Decimal(tax_rate)
    if tax < 0:
        raise ValueError("invalid tax")
    return (subtotal(lines) * (1 + tax)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
