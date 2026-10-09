"""工作目录解析与写沙箱（coding/tools/registry.py:155-223）。

沙箱是 auto 模式敢全放行的前提，所以除了"越界被拒"，还要证明软链接绕过也会被拦。
"""

import pytest
from zzhclaw.coding.tools import (
    get_cwd,
    get_tools_with_cwd,
    set_cwd,
    set_sandbox,
    write_file,
)
from zzhclaw.coding.tools.registry import _check_write_sandbox, _resolve_path


# ===== 路径解析 =====

def test_relative_paths_resolve_against_cwd(workspace):
    assert _resolve_path("a.txt") == str(workspace.cwd / "a.txt")
    assert _resolve_path("deep/../a.txt") == str(workspace.cwd / "a.txt")


def test_absolute_paths_are_normalized_without_rebasing(workspace):
    outside = "/tmp/whatever"
    assert _resolve_path(outside) == outside


def test_set_cwd_rejects_missing_directory(workspace, tmp_path):
    missing = str(tmp_path / "nope")

    assert set_cwd(missing) == f"错误: 目录不存在: {missing}"
    assert get_cwd() == str(workspace.cwd), "无效路径不应改变当前工作目录"


def test_set_cwd_returns_absolute_path_and_takes_effect(tmp_path):
    resolved = set_cwd(str(tmp_path))

    assert resolved == str(tmp_path)
    assert get_cwd() == str(tmp_path)


# ===== 写沙箱 =====

def test_paths_inside_cwd_are_allowed(workspace):
    assert _check_write_sandbox(str(workspace.cwd / "sub" / "a.txt")) is None


def test_paths_outside_cwd_are_rejected(workspace, tmp_path):
    error = _check_write_sandbox(str(tmp_path / "escape.txt"))

    assert error and "写入被沙箱拒绝" in error


def test_sibling_path_with_shared_prefix_is_not_treated_as_inside(workspace, tmp_path):
    """/tmp/x/cwd-evil 不该被当成 /tmp/x/cwd 的子路径（startswith 的经典坑）。"""
    sibling = str(workspace.cwd) + "-evil/a.txt"

    assert "写入被沙箱拒绝" in _check_write_sandbox(sibling)


def test_write_file_refuses_outside_and_creates_nothing(workspace, tmp_path):
    target = tmp_path / "outside.txt"

    result = write_file(str(target), "payload")

    assert "写入被沙箱拒绝" in result
    assert not target.exists()


def test_symlink_cannot_carve_a_way_out_of_the_sandbox(workspace, tmp_path):
    """cwd 内放一个指向外部的软链接，realpath 检查必须拦住它。"""
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (workspace.cwd / "link").symlink_to(outside_dir)

    result = write_file("link/payload.txt", "data")

    assert "写入被沙箱拒绝" in result
    assert not (outside_dir / "payload.txt").exists()


def test_turning_the_sandbox_off_allows_external_writes(workspace, tmp_path):
    set_sandbox(False)
    target = tmp_path / "outside.txt"

    assert write_file(str(target), "data").startswith("成功写入")
    assert target.read_text() == "data"
    set_sandbox(True)


# ===== 工具描述与实际状态一致 =====

def test_tool_descriptions_advertise_the_current_cwd(workspace):
    tools = {t["function"]["name"]: t["function"]["description"] for t in get_tools_with_cwd()}

    assert str(workspace.cwd) in tools["read_file"]
    assert str(workspace.cwd) in tools["run_bash"]


def test_write_file_description_reflects_sandbox_state(workspace):
    def description():
        return next(t["function"]["description"] for t in get_tools_with_cwd()
                    if t["function"]["name"] == "write_file")

    assert "写沙箱已启用" in description()
    set_sandbox(False)
    assert "写沙箱已关闭" in description()


def test_returned_tools_are_deep_copies_of_the_registry(workspace):
    """模型/UI 改工具描述不能污染全局 TOOLS。"""
    tools = get_tools_with_cwd()
    tools[0]["function"]["description"] = "被改坏了"

    from zzhclaw.coding.tools import TOOLS

    assert TOOLS[0]["function"]["description"] != "被改坏了"
