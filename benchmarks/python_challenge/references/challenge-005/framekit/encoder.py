def encode(payload):
    if not isinstance(payload, bytes):
        raise TypeError("bytes required")
    return len(payload).to_bytes(4, "big") + payload
