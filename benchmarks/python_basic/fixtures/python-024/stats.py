def summarize(values):
    return {
        "count": len(values),
        "sum": sum(values),
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
    }
