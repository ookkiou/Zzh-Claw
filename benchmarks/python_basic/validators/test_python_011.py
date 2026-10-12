import pytest
from retry import retry_call


def test_retries():
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("temporary")
        return 0

    assert retry_call(fn, 4) == 0 and len(calls) == 3


def test_original_exception():
    error = ValueError("last")
    calls = []

    def fn():
        calls.append(1)
        raise error

    with pytest.raises(ValueError) as caught:
        retry_call(fn, 2)
    assert caught.value is error and len(calls) == 2


def test_not_selected():
    calls = []

    def fn():
        calls.append(1)
        raise TypeError("fatal")

    with pytest.raises(TypeError):
        retry_call(fn, 5, (ValueError,))
    assert len(calls) == 1


@pytest.mark.parametrize("attempts", [0, -1, True, 1.5])
def test_invalid(attempts):
    with pytest.raises(ValueError):
        retry_call(lambda: 1, attempts)
