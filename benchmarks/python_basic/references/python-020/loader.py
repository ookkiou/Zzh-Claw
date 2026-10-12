from settings import Settings


def load_settings(mapping, env):
    data = {key: mapping[key] for key in ("host", "port", "debug") if key in mapping}
    for key in ("host", "port", "debug"):
        if "APP_" + key.upper() in env:
            data[key] = env["APP_" + key.upper()]
    return Settings(**data)
