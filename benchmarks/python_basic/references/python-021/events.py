class EventBus:
    def __init__(self):
        self.listeners = {}

    def on(self, event, callback):
        callbacks = self.listeners.setdefault(event, [])
        if callback not in callbacks:
            callbacks.append(callback)

    def off(self, event, callback):
        callbacks = self.listeners.get(event, [])
        if callback in callbacks:
            callbacks.remove(callback)

    def emit(self, event, value):
        return [fn(value) for fn in list(self.listeners.get(event, []))]
