class EventBus:
    listeners = {}

    def on(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)

    def off(self, event, callback):
        self.listeners[event].remove(callback)

    def emit(self, event, value):
        return [fn(value) for fn in self.listeners.get(event, [])]
