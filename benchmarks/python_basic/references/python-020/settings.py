from dataclasses import dataclass


@dataclass
class Settings:
    host: str = "localhost"
    port: int = 8000
    debug: bool = False

    def __post_init__(self):
        if not isinstance(self.host, str) or not self.host.strip():
            raise ValueError("host")
        if isinstance(self.port, bool) or not isinstance(self.port, (str, int)):
            raise ValueError("port")
        try:
            self.port = int(self.port)
        except (ValueError, TypeError):
            raise ValueError("port")
        if not 1 <= self.port <= 65535:
            raise ValueError("port")
        if isinstance(self.debug, str) and self.debug.lower() in {"true", "false"}:
            self.debug = self.debug.lower() == "true"
        if not isinstance(self.debug, bool):
            raise ValueError("debug")
