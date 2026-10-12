def subtotal(lines):
    return sum(float(price) * quantity for price, quantity in lines)
