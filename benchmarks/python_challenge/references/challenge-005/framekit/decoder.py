from .errors import FrameError


class Decoder:
    def __init__(self, max_size=1024):
        if isinstance(max_size, bool) or not isinstance(max_size, int) or max_size < 0:
            raise ValueError("max_size")
        self.max_size = max_size
        self.reset()

    def reset(self):
        self.buffer = bytearray()
        self.closed = False
        self.failed = False

    def feed(self, data):
        if self.closed or self.failed:
            raise FrameError("unavailable")
        if not isinstance(data, bytes):
            raise TypeError("bytes required")
        self.buffer.extend(data)
        result = []
        while len(self.buffer) >= 4:
            length = int.from_bytes(self.buffer[:4], "big")
            if length > self.max_size:
                self.failed = True
                self.buffer.clear()
                raise FrameError("too large")
            if len(self.buffer) < 4 + length:
                break
            result.append(bytes(self.buffer[4 : 4 + length]))
            del self.buffer[: 4 + length]
        return result

    def finish(self):
        if self.closed or self.failed:
            raise FrameError("unavailable")
        self.closed = True
        if self.buffer:
            self.failed = True
            raise FrameError("truncated")
        return None
