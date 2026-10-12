def summarize(values):
    count, total, low, high = 0, 0, None, None
    for value in values:
        count += 1
        total += value
        low = value if low is None else min(low, value)
        high = value if high is None else max(high, value)
    return {
        "count": count,
        "sum": total,
        "min": low,
        "max": high,
        "mean": total / count if count else None,
    }
