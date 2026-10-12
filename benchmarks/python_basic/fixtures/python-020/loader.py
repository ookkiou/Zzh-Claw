from settings import Settings


def load_settings(mapping, env):
    return Settings(**mapping)
