import ast
import inspect

import stats


def test_stats():
    assert stats.summarize(iter([3, -1, 4])) == {
        "count": 3,
        "sum": 6,
        "min": -1,
        "max": 4,
        "mean": 2,
    }


def test_empty():
    assert stats.summarize(iter([])) == {
        "count": 0,
        "sum": 0,
        "min": None,
        "max": None,
        "mean": None,
    }


def test_single_pass():
    class OnePass:
        used = False

        def __iter__(self):
            assert not self.used
            self.used = True
            yield from [1, 2, 3]

    assert stats.summarize(OnePass())["mean"] == 2


def test_no_materialization():
    tree = ast.parse(inspect.getsource(stats))
    assert not any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id in {"list", "tuple", "sorted"}
        for n in ast.walk(tree)
    )
