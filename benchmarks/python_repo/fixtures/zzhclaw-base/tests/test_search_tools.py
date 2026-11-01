"""代码检索工具（grep_files / glob_files，registry.py:657-731）。"""

import pytest
from zzhclaw.coding.tools import glob_files, grep_files


@pytest.fixture
def tree(workspace):
    """一棵小项目树，含一个应当被忽略的 node_modules。"""
    workspace.write("src/app.py", "import os\n\ndef handler(request):\n    return 1\n")
    workspace.write("src/util.py", "def helper():\n    pass\n")
    workspace.write("tests/test_app.py", "def test_handler():\n    assert True\n")
    workspace.write("README.md", "# Demo\n\nSee handler for details.\n")
    workspace.write("node_modules/left-pad/index.js", "module.exports = function handler() {}\n")
    return workspace


# ===== grep_files =====

def test_grep_reports_relative_path_line_and_text(tree):
    result = grep_files("def handler", path="src")

    assert "app.py:3: def handler(request):" in result
    assert result.startswith("找到 1 处匹配")


def test_grep_accepts_regex(tree):
    assert "util.py:1: def helper():" in grep_files(r"def \w+\(\)")


def test_grep_without_matches_reports_scan_count(tree):
    assert grep_files("不存在的东西", path="src").startswith("未找到匹配: 不存在的东西")


def test_grep_include_filter_narrows_file_types(tree):
    result = grep_files("handler", include="*.py")

    assert "README.md" not in result
    assert "test_app.py" in result


def test_grep_ignore_case(tree):
    assert "README.md" in grep_files("see handler", path=".", include="*.md", ignore_case=True)
    assert grep_files("see handler", path=".", include="*.md").startswith("未找到匹配")


def test_grep_skips_ignored_directories(tree):
    assert "node_modules" not in grep_files("handler")


def test_grep_respects_max_results(tree):
    result = grep_files("def", max_results=2)

    assert "找到 2 处匹配" in result


def test_grep_rejects_invalid_regex_without_crashing(tree):
    assert grep_files("def (", path="src").startswith("错误: 无效的正则表达式")


def test_grep_missing_directory_is_reported(tree):
    assert grep_files("x", path="ghost").startswith("错误: 目录不存在")


def test_grep_survives_binary_like_files(tree):
    (tree.cwd / "blob.bin").write_bytes(b"\x00\xff\xfe not utf-8 at all")

    assert grep_files("def", path=".").startswith("找到")


# ===== glob_files =====

def test_glob_matches_by_pattern(tree):
    result = glob_files("*.md", path=".")

    assert result.startswith("找到 1 个文件")
    assert "README.md" in result


def test_glob_recurses_with_double_star(tree):
    result = glob_files("**/*.py")

    assert "src/app.py" in result
    assert "tests/test_app.py" in result
    assert "node_modules" not in result


def test_glob_results_are_sorted(tree):
    entries = glob_files("**/*.py").splitlines()[2:]

    assert entries == sorted(entries)


def test_glob_respects_max_results(tree):
    assert "找到 1 个文件" in glob_files("**/*.py", max_results=1)


def test_glob_without_matches_is_reported(tree):
    assert glob_files("**/*.rsv").startswith("未找到匹配文件")


def test_glob_missing_directory_is_reported(tree):
    assert glob_files("*", path="ghost").startswith("错误: 目录不存在")
