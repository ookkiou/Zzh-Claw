from logging_utils import redact


def test_nested():
    value = {
        "PASSWORD": "secret",
        "items": [{"Token": None, "name": "x"}],
        "tuple": ({"api_key": 123},),
        1: "ok",
    }
    result = redact(value)
    assert result == {
        "PASSWORD": "***",
        "items": [{"Token": "***", "name": "x"}],
        "tuple": ({"api_key": "***"},),
        1: "ok",
    }
    assert value["PASSWORD"] == "secret" and value["items"][0]["Token"] is None
    result["items"].append(1)
    assert len(value["items"]) == 1


def test_scalars():
    assert redact(None) is None and redact("token") == "token" and redact(0) == 0
