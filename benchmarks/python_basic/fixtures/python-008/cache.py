class TTLCache:
    def __init__(self, ttl, clock):
        self.ttl, self.clock, self.data = ttl, clock, {}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)
