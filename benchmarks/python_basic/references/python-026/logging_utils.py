def redact(value):
    if isinstance(value, dict):
        return {
            key: "***"
            if isinstance(key, str) and key.lower() in {"password", "token", "api_key"}
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value
