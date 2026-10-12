def clamp(value, lower, upper):
    if lower > upper:
        raise ValueError("inverted bounds")
    return min(max(value, lower), upper)
