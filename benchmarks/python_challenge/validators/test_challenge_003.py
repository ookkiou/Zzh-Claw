import pytest
from queuekit import LeaseQueue


@pytest.mark.parametrize("ttl", [0, -1, -100])
def test_ttl(ttl):
    with pytest.raises(ValueError):
        LeaseQueue(lambda: 0, ttl)


def test_deadline_and_stale_ack():
    now = [0]
    q = LeaseQueue(lambda: now[0], 10)
    q.put("a", {"v": [1]})
    first = q.claim()
    assert first.deadline == 10
    assert q.claim() is None
    now[0] = 10
    assert q.ack("a", first.token) is False
    second = q.claim()
    assert second.key == "a" and second.token != first.token and second.deadline == 20
    assert q.ack("a", first.token) is False
    assert q.ack("a", second.token) is True
    assert q.claim() is None
    q.put("a", {})
    third = q.claim()
    assert third.token not in {first.token, second.token}
    assert not q.ack("a", second.token)
    assert q.ack("a", third.token)


def test_ownership_fifo_and_duplicates():
    now = [0]
    q = LeaseQueue(lambda: now[0], 2)
    payload = {"v": [1]}
    q.put("a", payload)
    payload["v"].append(9)
    q.put("b", {})
    a = q.claim()
    assert a.payload == {"v": [1]}
    a.payload["v"].append(8)
    assert q.claim().key == "b"
    now[0] = 2
    with pytest.raises(ValueError):
        q.put("a", {})
    again = q.claim()
    assert again.key == "a" and again.payload == {"v": [1]}
    assert not q.ack("missing", "x")
    assert not q.ack("b", "wrong")
    q2 = LeaseQueue(lambda: 0)
    assert q2.claim() is None
