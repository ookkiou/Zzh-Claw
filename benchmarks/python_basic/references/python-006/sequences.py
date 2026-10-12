def chunked(items, size):
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ValueError("invalid size")
    result, current = [], []
    for item in items:
        current.append(item)
        if len(current) == size:
            result.append(current)
            current = []
    if current:
        result.append(current)
    return result
