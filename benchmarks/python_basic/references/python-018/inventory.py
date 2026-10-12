def reserve(product, quantity):
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("invalid quantity")
    if quantity > product.stock:
        raise ValueError("insufficient stock")
    product.stock -= quantity
    return product.stock
