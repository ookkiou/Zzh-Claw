class LRUCache:
    def __init__(self, capacity):
        self.capacity, self.data = capacity, {}

    def put(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)
