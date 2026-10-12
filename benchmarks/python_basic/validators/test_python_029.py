from query import parse_query


def test_repeated():
    assert parse_query("a=1&a=2&b=&flag") == {"a": ["1", "2"], "b": [""], "flag": [""]}


def test_decode():
    assert parse_query("?name=%E4%BD%A0%E5%A5%BD&x=a+b&v=a%3Db") == {
        "name": ["你好"],
        "x": ["a b"],
        "v": ["a=b"],
    }


def test_edges():
    assert parse_query("") == {} and parse_query("?") == {}
    assert parse_query("a=x=y") == {"a": ["x=y"]}
    assert parse_query("??x=1") == {"?x": ["1"]}
