from datetime import timezone


def to_utc_iso(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("naive datetime")
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
