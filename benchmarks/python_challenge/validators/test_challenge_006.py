import copy

import pytest
from configkit import load


@pytest.fixture
def base():
    return {
        "host": "localhost",
        "port": 80,
        "debug": True,
        "database": {"host": "db", "port": 5432},
        "labels": ["a"],
    }


def test_precedence_and_ownership(base):
    before = copy.deepcopy(base)
    over = {"database": {"port": 6000}, "labels": ["b"]}
    saved = copy.deepcopy(over)
    env = {"APP_PORT": "00443", "APP_DEBUG": "FaLsE", "IGNORE": "x"}
    result = load(base, over, env)
    assert result == {
        "host": "localhost",
        "port": 443,
        "debug": False,
        "database": {"host": "db", "port": 6000},
        "labels": ["b"],
    }
    result["database"]["host"] = "changed"
    result["labels"].append("x")
    assert base == before and over == saved


def test_delete_optional_and_required(base):
    assert "labels" not in load(base, {"labels": None}, {})
    with pytest.raises(ValueError):
        load(base, {"database": {"host": None}}, {})
    assert base["database"]["host"] == "db"


@pytest.mark.parametrize(
    "over",
    [
        {"port": True},
        {"port": 0},
        {"port": 65536},
        {"debug": 1},
        {"host": " "},
        {"labels": "x"},
        {"labels": [1]},
        {"extra": 1},
        {"database": {"extra": 1}},
        {"database": None},
        {"database": {"port": False}},
    ],
)
def test_schema(base, over):
    before = copy.deepcopy(base)
    with pytest.raises(ValueError):
        load(base, over, {})
    assert base == before


@pytest.mark.parametrize(
    "key,value",
    [
        ("APP_PORT", "+1"),
        ("APP_PORT", " 1"),
        ("APP_PORT", "1.0"),
        ("APP_PORT", "١"),
        ("APP_PORT", "65536"),
        ("APP_DEBUG", " false"),
        ("APP_DEBUG", "yes"),
    ],
)
def test_env_strict(base, key, value):
    before = copy.deepcopy(base)
    with pytest.raises(ValueError):
        load(base, {}, {key: value})
    assert base == before


@pytest.mark.parametrize(
    "raw,expected", [("0", False), ("1", True), ("TRUE", True), ("false", False)]
)
def test_booleans(base, raw, expected):
    assert load(base, {}, {"APP_DEBUG": raw})["debug"] is expected
