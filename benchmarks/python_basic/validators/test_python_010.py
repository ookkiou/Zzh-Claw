import pytest
from csv_utils import parse_csv


def test_quotes():
    assert parse_csv('name,note\n"a,b","say ""hi"""\n') == [
        {"name": "a,b", "note": 'say "hi"'}
    ]


def test_newline():
    assert parse_csv('a,b\n"x\ny",z\n\n') == [{"a": "x\ny", "b": "z"}]


def test_edges():
    assert parse_csv("") == [] and parse_csv("a,b\n") == []
    assert parse_csv("a,b\nx,\n") == [{"a": "x", "b": ""}]


@pytest.mark.parametrize("text", ["a,a\n1,2", "a,\n1,2", "a,b\n1", "a\n1,2"])
def test_invalid(text):
    with pytest.raises(ValueError):
        parse_csv(text)
