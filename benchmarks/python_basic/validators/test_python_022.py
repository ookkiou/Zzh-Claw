import legacy
import pytest
import slug
from legacy import make_slug


def test_normalize():
    assert slug.slugify("  Hello, WORLD!  ") == "hello-world"
    assert slug.slugify("a---b", "_") == "a_b"
    assert slug.slugify("中文!?") == "" and make_slug("a   B!") == "a-b"


def test_separator():
    with pytest.raises(ValueError):
        slug.slugify("a", ".")


def test_delegate(monkeypatch):
    original = slug.slugify

    def replacement(text, separator="-"):
        return "delegated"

    monkeypatch.setattr(slug, "slugify", replacement)
    # 模块引用和 from import（含别名）均是合法委托，不强制动态绑定。
    for name, value in list(vars(legacy).items()):
        if value is original:
            monkeypatch.setattr(legacy, name, replacement)
    assert make_slug("anything") == "delegated"
