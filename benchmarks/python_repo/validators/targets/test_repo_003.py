import pytest

from zzhclaw.coding.tools import registry


@pytest.mark.parametrize("value", [0, -1, -100, True, False, 1.5, "2", None])
@pytest.mark.parametrize("tool", ["grep_files", "glob_files"])
def test_invalid_limit_is_a_result_not_an_exception(tool, value, workspace):
    workspace.write("sample.py", "sample")
    fn = getattr(registry, tool)
    result = fn("sample" if tool == "grep_files" else "*", max_results=value)
    assert result.startswith("错误:")


@pytest.mark.parametrize("tool", ["grep_files", "glob_files"])
def test_invalid_limit_does_not_scan(tool, monkeypatch):
    def scan(*args, **kwargs):
        raise AssertionError("invalid input reached scan")

    monkeypatch.setattr(registry.os, "walk", scan)
    monkeypatch.setattr(registry.glob, "glob", scan)
    result = getattr(registry, tool)("*", max_results=0)
    assert result.startswith("错误:")
