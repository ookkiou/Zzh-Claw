def paginate(items, page, size):
    for value in (page, size):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("positive integer required")
    return {
        "items": items[(page - 1) * size : page * size],
        "total": len(items),
        "pages": (len(items) + size - 1) // size,
        "page": page,
    }
