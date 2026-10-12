def validate(config):
    if set(config) - {"host", "port", "debug", "database", "labels"}:
        raise ValueError("unknown config")
    if not isinstance(config.get("host"), str) or not config["host"].strip():
        raise ValueError("host")
    port = config.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port")
    if not isinstance(config.get("debug"), bool):
        raise ValueError("debug")
    db = config.get("database")
    if not isinstance(db, dict) or set(db) != {"host", "port"}:
        raise ValueError("database")
    if not isinstance(db["host"], str) or not db["host"].strip():
        raise ValueError("database host")
    if (
        isinstance(db["port"], bool)
        or not isinstance(db["port"], int)
        or not 1 <= db["port"] <= 65535
    ):
        raise ValueError("database port")
    if "labels" in config and (
        not isinstance(config["labels"], list)
        or any(not isinstance(v, str) for v in config["labels"])
    ):
        raise ValueError("labels")
    return config
