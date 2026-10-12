from pricing import subtotal


def checkout(lines, tax_rate="0"):
    return round(subtotal(lines) * (1 + float(tax_rate)), 2)
