import users


def test_normalize():
    rows = [{"email": " A@B.COM ", "name": " Alice ", "extra": 1}, {"email": "c@d"}]
    assert users.normalize_users(rows) == [
        {"email": "a@b.com", "name": "Alice", "extra": 1},
        {"email": "c@d", "name": ""},
    ]
    assert rows[0]["email"] == " A@B.COM " and "name" not in rows[1]
    assert users.normalize_email(" X@Y ") == "x@y"


def test_delegate(monkeypatch):
    monkeypatch.setattr(users, "normalize_email", lambda value: "override")
    assert users.normalize_users([{"email": "a"}])[0]["email"] == "override"


def test_empty():
    assert users.normalize_users(iter([])) == []
