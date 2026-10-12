import pytest
from pagination import paginate


def test_pages():
    values = [1, 2, 3, 4, 5]
    assert paginate(values, 1, 2) == {
        "items": [1, 2],
        "total": 5,
        "pages": 3,
        "page": 1,
    }
    assert paginate(values, 3, 2)["items"] == [5]
    assert paginate(values, 4, 2)["items"] == [] and values == [1, 2, 3, 4, 5]


def test_empty():
    assert paginate([], 1, 2) == {"items": [], "total": 0, "pages": 0, "page": 1}


@pytest.mark.parametrize("p,s", [(0, 2), (1, 0), (-1, 2), (True, 2), (1, 1.5)])
def test_invalid(p, s):
    with pytest.raises(ValueError):
        paginate([], p, s)
