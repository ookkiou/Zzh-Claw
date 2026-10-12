import pytest
from text_utils import normalize_whitespace


@pytest.mark.parametrize(
    "text,expected",
    [
        ("", ""),
        ("  \t\n", ""),
        ("  alpha\t beta\n gamma  ", "alpha beta gamma"),
        ("中\u3000文", "中 文"),
        ("a-b", "a-b"),
    ],
)
def test_normalize(text, expected):
    assert normalize_whitespace(text) == expected
