def reserve(product, quantity):
    product.stock -= quantity
    return product.stock
