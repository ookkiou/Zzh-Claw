class TTLCache:
    def __init__(self, ttl, clock):
        if ttl <= 0:
            raise ValueError("invalid ttl")
        self.ttl, self.clock, self.data = ttl, clock, {}

    def set(self, key, value):
        self.data[key] = (value, self.clock() + self.ttl)

    def get(self, key, default=None):
        if key not in self.data:
            return default
        value, expiry = self.data[key]
        if self.clock() >= expiry:
            del self.data[key]
            return default
        return value
