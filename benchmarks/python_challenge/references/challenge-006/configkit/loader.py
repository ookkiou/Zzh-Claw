from .merge import merge
from .schema import validate


def load(defaults, overrides, env):
    result = merge(defaults, overrides)
    if "APP_PORT" in env:
        raw = env["APP_PORT"]
        if not isinstance(raw, str) or not raw.isascii() or not raw.isdecimal():
            raise ValueError("APP_PORT")
        result["port"] = int(raw)
    if "APP_DEBUG" in env:
        raw = env["APP_DEBUG"]
        if not isinstance(raw, str) or raw.lower() not in {"true", "false", "1", "0"}:
            raise ValueError("APP_DEBUG")
        result["debug"] = raw.lower() in {"true", "1"}
    return validate(result)
