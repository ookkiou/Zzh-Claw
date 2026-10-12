import pytest
from loader import load_settings
from settings import Settings


def test_defaults():
    assert load_settings({}, {}) == Settings("localhost", 8000, False)


def test_precedence():
    mapping = {"host": "local", "port": 9000, "debug": False}
    env = {"APP_PORT": "8080", "APP_DEBUG": "TRUE"}
    value = load_settings(mapping, env)
    assert value == Settings("local", 8080, True) and isinstance(value.port, int)
    assert mapping["port"] == 9000 and env["APP_DEBUG"] == "TRUE"


@pytest.mark.parametrize(
    "mapping",
    [
        {"port": 0},
        {"port": "65536"},
        {"port": True},
        {"port": 1.2},
        {"debug": "yes"},
        {"host": ""},
    ],
)
def test_invalid(mapping):
    with pytest.raises(ValueError):
        load_settings(mapping, {})
