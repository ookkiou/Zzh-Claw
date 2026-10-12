import pytest
from flags import parse_bool


@pytest.mark.parametrize("value", ["TRUE", " 1 ", "Yes", "on", True])
def test_true(value):
    assert parse_bool(value) is True


@pytest.mark.parametrize("value", ["False", "0", " NO ", "Off", False])
def test_false(value):
    assert parse_bool(value) is False


@pytest.mark.parametrize("value", ["", None, 1, 0, [], "maybe"])
def test_invalid(value):
    with pytest.raises(ValueError):
        parse_bool(value)
