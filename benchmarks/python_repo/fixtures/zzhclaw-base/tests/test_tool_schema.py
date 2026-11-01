"""工具表与分发的一致性（registry.py:145-152, 227-459, 888-924）。

最有价值的一条：给模型声明了 schema 却忘了在 execute_tool 里分发，是只有跑起来
才会炸的 bug；这里把它钉成静态一致性检查。
"""

import pytest
from zzhclaw.coding.tools import (
    READONLY_TOOLS,
    TOOLS,
    WRITE_TOOLS,
    execute_tool,
    is_readonly_tool,
)
from zzhclaw.coding.tools import registry

NETWORK_TOOLS = {"web_search", "fetch_webpage"}


def declared_names():
    return [t["function"]["name"] for t in TOOLS]


@pytest.fixture
def no_network(monkeypatch):
    """把联网工具换成桩，分发一致性检查绝不碰真实网络。"""
    monkeypatch.setattr(registry, "web_search", lambda *a, **k: "STUB 搜索")
    monkeypatch.setattr(registry, "fetch_webpage", lambda *a, **k: "STUB 网页")


# ===== schema 形状 =====

def test_tool_names_are_unique():
    names = declared_names()

    assert len(names) == len(set(names)), f"重复的工具声明: {names}"


def test_every_tool_declares_a_valid_function_schema():
    for tool in TOOLS:
        assert tool["type"] == "function"
        fn = tool["function"]
        assert fn["name"] and fn["description"]
        assert fn["parameters"]["type"] == "object"
        assert isinstance(fn["parameters"]["properties"], dict)


def test_every_required_parameter_is_declared_in_properties():
    for tool in TOOLS:
        fn = tool["function"]
        props = set(fn["parameters"]["properties"])
        for required in fn["parameters"].get("required", []):
            assert required in props, f"{fn['name']} 要求了未定义的参数 {required}"


# ===== 声明与分发的一致性 =====

@pytest.mark.parametrize("name", sorted(declared_names()))
def test_every_declared_tool_is_dispatched(name, no_network):
    """execute_tool 必须认识 schema 里声明的每个工具。"""
    try:
        result = execute_tool(name, {})
    except KeyError:
        return  # 命中了分发分支，只是空参数缺必需 key
    assert not result.startswith("未知工具"), f"{name} 有 schema 但没有实现分支"


def test_undeclared_tool_is_reported_not_raised(no_network):
    assert execute_tool("delete_production", {}) == "未知工具: delete_production"


def test_unclassified_tools_default_to_requiring_confirmation():
    """漏进清单的新工具按写处理：smart 模式默认询问，而不是默认放行。"""
    unclassified = set(declared_names()) - READONLY_TOOLS - WRITE_TOOLS

    for name in unclassified:
        assert not is_readonly_tool(name)


def test_readonly_and_write_sets_are_disjoint_and_declared():
    names = set(declared_names())

    assert READONLY_TOOLS <= names, "只读清单里出现了未声明的工具"
    assert WRITE_TOOLS <= names, "写清单里出现了未声明的工具"
    assert not (READONLY_TOOLS & WRITE_TOOLS), "同一工具不能既只读又写"


def test_all_mutating_tools_are_classified_as_write():
    """smart 模式靠这份清单决定放行；漏分类等于自动批准写操作。"""
    side_effect_free = {"run_bash", "write_file", "edit_file"}

    assert side_effect_free <= WRITE_TOOLS


@pytest.mark.parametrize("name, expected", [
    ("read_file", True),
    ("grep_files", True),
    ("glob_files", True),
    ("web_search", True),
    ("fetch_webpage", True),
    ("Skill", True),
    ("write_file", False),
    ("edit_file", False),
    ("run_bash", False),
    ("不存在的工具", False),
])
def test_is_readonly_tool(name, expected):
    assert is_readonly_tool(name) is expected


# ===== 参数默认值 =====

def test_grep_defaults_are_applied(workspace, no_network):
    workspace.write("a.py", "def f(): pass\n")

    assert "a.py:1: def f(): pass" in execute_tool("grep_files", {"pattern": "def f"})


def test_glob_defaults_search_from_cwd(workspace):
    workspace.write("a.py", "")

    assert "a.py" in execute_tool("glob_files", {"pattern": "*.py"})


def test_edit_defaults_to_single_replacement(workspace):
    workspace.write("a.txt", "x x x")

    result = execute_tool("edit_file", {"path": "a.txt", "old_text": "x x", "new_text": "y"})

    assert "（替换 1 处）" in result
    assert (workspace.cwd / "a.txt").read_text(encoding="utf-8") == "y x"


def test_skill_tool_is_optional_name(workspace):
    result = execute_tool("Skill", {})

    assert "当前没有可用的 skill" in result or "可用的 skill" in result


def test_web_search_results_reach_the_model_through_a_stub(no_network):
    assert execute_tool("web_search", {"query": "anything"}) == "STUB 搜索"
