def top_k(items, k, key):
    if isinstance(k, bool) or not isinstance(k, int) or k < 0:
        raise ValueError("invalid k")
    return sorted(items, key=key, reverse=True)[:k]
