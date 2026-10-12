from copy import deepcopy

from .models import Lease


class LeaseQueue:
    def __init__(self, clock, ttl=10):
        if ttl <= 0:
            raise ValueError("ttl")
        self.clock = clock
        self.ttl = ttl
        self.items = []
        self.counter = 0

    def put(self, key, payload):
        if any(item["key"] == key for item in self.items):
            raise ValueError("duplicate key")
        self.items.append(
            {"key": key, "payload": deepcopy(payload), "token": None, "until": None}
        )

    def claim(self):
        now = self.clock()
        for item in self.items:
            if item["token"] is None or now >= item["until"]:
                self.counter += 1
                item["token"] = str(self.counter)
                item["until"] = now + self.ttl
                return Lease(
                    item["key"], deepcopy(item["payload"]), item["token"], item["until"]
                )
        return None

    def ack(self, key, token):
        now = self.clock()
        for item in self.items:
            if item["key"] == key:
                if (
                    item["token"] is None
                    or token != item["token"]
                    or now >= item["until"]
                ):
                    return False
                self.items.remove(item)
                return True
        return False
