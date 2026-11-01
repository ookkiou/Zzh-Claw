"""文件读写与增量编辑的工具契约（registry.py:463-577）。

这些字符串是模型看到的唯一反馈来源，所以错误信息本身也是被测接口。
"""

import threading

import pytest
from zzhclaw.coding.tools import edit_file, read_file, write_file
from zzhclaw.coding.tools.registry import _file_lock

_real_file_lock = _file_lock


def _quick_lock(path, timeout=10.0):
    """把默认 10s 的等锁时间压到 0.2s，免得测试真等 10 秒。"""
    return _real_file_lock(path, timeout=0.2)


# ===== read_file =====

def test_read_file_returns_content_verbatim(workspace):
    workspace.write("note.txt", "第一行\n第二行  \n")

    assert read_file("note.txt") == "第一行\n第二行  \n"


def test_read_file_reports_missing_path_as_result_not_exception(workspace):
    assert read_file("nope.txt").startswith("错误:")


# ===== write_file =====

def test_write_file_creates_parent_directories(workspace):
    result = write_file("deep/nested/a.txt", "内容")

    assert result == f"成功写入: {workspace.cwd / 'deep/nested/a.txt'}"
    assert (workspace.cwd / "deep/nested/a.txt").read_text(encoding="utf-8") == "内容"


def test_write_file_overwrites_existing_content(workspace):
    workspace.write("a.txt", "旧")

    write_file("a.txt", "新")

    assert read_file("a.txt") == "新"


def test_write_file_leaves_a_sibling_lock_file(workspace):
    """旁路锁文件是设计的一部分（.gitignore 已覆盖），钉住以免被"优化"掉。"""
    write_file("a.txt", "x")

    assert (workspace.cwd / "a.txt.lock").exists()


# ===== edit_file =====

def test_edit_replaces_the_unique_match(workspace):
    workspace.write("app.py", "def f():\n    return 1\n")

    result = edit_file("app.py", "    return 1", "    return 2")

    assert result == f"成功编辑: {workspace.cwd / 'app.py'}（替换 1 处）"
    assert read_file("app.py") == "def f():\n    return 2\n"


def test_edit_matches_substring_regardless_of_leading_indentation(workspace):
    workspace.write("app.py", "    return 1\n")

    result = edit_file("app.py", "return 1", "return 2")

    assert "成功编辑" in result and "（替换 1 处）" in result
    assert read_file("app.py") == "    return 2\n"


def test_edit_rejects_ambiguous_match_and_writes_nothing(workspace):
    workspace.write("a.txt", "x x x")

    result = edit_file("a.txt", "x", "y")

    assert "找到 3 处匹配" in result and "replace_all=true" in result
    assert read_file("a.txt") == "x x x"


def test_edit_with_replace_all_swaps_every_occurrence(workspace):
    workspace.write("a.txt", "x-x-x")

    result = edit_file("a.txt", "x", "y", replace_all=True)

    assert "（替换 3 处）" in result
    assert read_file("a.txt") == "y-y-y"


def test_edit_reports_when_text_is_not_found(workspace):
    workspace.write("a.txt", "内容")

    assert "未找到要替换的文本" in edit_file("a.txt", "不存在", "别的")


def test_edit_rejects_noop_change(workspace):
    workspace.write("a.txt", "内容")

    assert "无需修改" in edit_file("a.txt", "内容", "内容")


def test_edit_on_missing_file_reports_path(workspace):
    assert "文件不存在" in edit_file("ghost.txt", "a", "b")


def test_failed_edit_preserves_original_file(workspace):
    workspace.write("a.txt", "original")

    edit_file("a.txt", "nomatch", "whatever")

    assert read_file("a.txt") == "original"


# ===== 并发保护 =====

def test_file_lock_serialises_contending_writers(workspace):
    """两个写者争同一个文件时，后到者要么等待、要么超时，不能悄悄丢更新。"""
    target = str(workspace.cwd / "shared.txt")
    held = threading.Event()
    release = threading.Event()

    def holder():
        with _file_lock(target):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    held.wait(2)

    with pytest.raises(TimeoutError):
        with _file_lock(target, timeout=0.2):
            pass

    release.set()
    thread.join(2)

    with _file_lock(target, timeout=1):
        pass  # 锁已释放，能重新拿到


def test_write_file_returns_friendly_timeout_when_lock_is_stuck(workspace, monkeypatch):
    target = str(workspace.cwd / "a.txt")
    held, release = threading.Event(), threading.Event()

    def holder():
        with _file_lock(target):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    held.wait(2)

    monkeypatch.setattr("zzhclaw.coding.tools.registry._file_lock", _quick_lock)
    try:
        result = write_file("a.txt", "内容")
    finally:
        release.set()
        thread.join(2)

    assert "另一个任务正在写该文件" in result


# ===== 文件锁之外：编辑的读-改-写是原子的 =====

def test_edit_conflicting_writer_is_reported_not_applied(workspace, monkeypatch):
    target = str(workspace.cwd / "a.txt")
    workspace.write("a.txt", "hello")
    held, release = threading.Event(), threading.Event()

    def holder():
        with _file_lock(target):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    held.wait(2)

    # 把默认 10s 等待压到 0.2s，避免测试真的等 10 秒
    monkeypatch.setattr("zzhclaw.coding.tools.registry._file_lock", _quick_lock)
    try:
        result = edit_file("a.txt", "hello", "world")
    finally:
        release.set()
        thread.join(2)

    assert "另一个任务正在编辑该文件" in result
    assert read_file("a.txt") == "hello"
