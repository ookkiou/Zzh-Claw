"""Skill 发现与加载（registry.py:100-133, 733-885）。"""

import pytest
from zzhclaw.coding.tools import (
    create_skill,
    get_skills_dir,
    get_skills_dirs,
    list_skills,
    load_skill,
    set_skills_dir,
    skill_tool,
)
from zzhclaw.coding.tools.registry import _parse_frontmatter

FM = '---\nname: {name}\ndescription: 需要改动前先跑测试\n---\n'


# ===== frontmatter 解析 =====

def test_parse_frontmatter_splits_meta_and_body():
    meta, body = _parse_frontmatter('---\nname: a\ndescription: "带引号的描述"\n---\n正文\n第二行')

    assert meta == {"name": "a", "description": "带引号的描述"}
    assert body == "正文\n第二行"


def test_parse_frontmatter_without_marker_returns_whole_text():
    meta, body = _parse_frontmatter("# 只有正文")

    assert meta == {}
    assert body == "# 只有正文"


def test_parse_frontmatter_with_unterminated_marker_is_treated_as_body():
    meta, body = _parse_frontmatter("---\nname: a\n没有闭合")

    assert meta == {}
    assert body == "---\nname: a\n没有闭合"


def test_parse_frontmatter_ignores_lines_without_colon():
    meta, _ = _parse_frontmatter("---\n裸文本\nname: a\n---\n正文")

    assert meta == {"name": "a"}


# ===== 发现 =====

def test_project_and_global_skills_are_both_listed(workspace):
    workspace.add_skill("proj", FM.format(name="proj"))
    workspace.add_skill("glob", FM.format(name="glob"), scope="global")

    found = {s["name"]: s["scope"] for s in list_skills()}

    assert found == {"proj": "project", "glob": "global"}


def test_frontmatter_name_overrides_directory_name(workspace):
    workspace.add_skill("folder-name", FM.format(name="真实名字"))

    skill = list_skills()[0]

    assert skill["name"] == "真实名字"
    assert skill["dir"] == "folder-name"


def test_project_skill_shadows_global_with_same_name(workspace):
    workspace.add_skill("dup", FM.format(name="dup") + "项目版指令", scope="global")
    workspace.add_skill("dup", FM.format(name="dup") + "项目版优先", scope="project")

    skills = [s for s in list_skills() if s["name"] == "dup"]

    assert len(skills) == 1
    assert skills[0]["scope"] == "project"


def test_skill_directories_are_project_first():
    assert [d["scope"] for d in get_skills_dirs()] == ["project", "global"]


def test_missing_skill_directory_is_skipped(workspace):
    assert list_skills() == []


# ===== 加载 =====

def test_load_returns_instructions_with_a_header(workspace):
    workspace.add_skill("tdd", FM.format(name="tdd") + "第一步：先写失败的测试")

    content = load_skill("tdd")

    assert content.startswith("[已加载 skill: tdd（project）]")
    assert "描述: 需要改动前先跑测试" in content
    assert "第一步：先写失败的测试" in content


def test_load_falls_back_to_directory_name_when_frontmatter_absent(workspace):
    workspace.add_skill("bare", "只有正文")

    assert "[已加载 skill: bare（project）]" in load_skill("bare")


def test_load_unknown_skill_lists_what_is_available(workspace):
    workspace.add_skill("known", FM.format(name="known"))

    result = load_skill("ghost")

    assert "未找到 skill 'ghost'" in result
    assert "可用 skill: known" in result


def test_load_blocks_path_traversal(workspace):
    (workspace.global_skills_dir.parent / "secret.md").write_text("机密", encoding="utf-8")
    workspace.add_skill("safe", FM.format(name="safe"))

    result = load_skill("../../secret")

    assert "未找到 skill" in result
    assert "机密" not in result


def test_skill_tool_without_name_lists_everything(workspace):
    workspace.add_skill("one", FM.format(name="one"))

    out = skill_tool()

    assert "可用的 skill" in out
    assert "[project] one: 需要改动前先跑测试" in out


@pytest.mark.parametrize("arg", [None, "", "  ", "list", "LS"])
def test_skill_tool_treats_list_aliases_as_listing(workspace, arg):
    assert "当前没有可用的 skill" in skill_tool(arg)


def test_skill_tool_with_name_loads(workspace):
    workspace.add_skill("one", FM.format(name="one"))

    assert "[已加载 skill: one" in skill_tool("one")


# ===== 创建 =====

def test_create_skill_writes_an_editable_template(workspace):
    ok, message = create_skill("my-flow", scope="project")

    assert ok is True
    path = workspace.cwd / ".zzhclaw" / "skills" / "my-flow" / "SKILL.md"
    assert path.exists()
    assert "description" in path.read_text(encoding="utf-8")

    assert list_skills()[0]["name"] == "my-flow"


def test_create_skill_in_global_scope(workspace):
    ok, _ = create_skill("shared-tool", scope="global")

    assert ok is True
    assert (workspace.global_skills_dir / "shared-tool" / "SKILL.md").exists()


@pytest.mark.parametrize("name, reason", [
    ("", "名称不能为空"),
    ("带 空格", "只能含字母"),
    ("中文skill", "只能含字母"),
    ("../escape", "只能含字母"),
])
def test_create_skill_rejects_bad_names(workspace, name, reason):
    ok, message = create_skill(name)

    assert ok is False
    assert reason in message


def test_create_skill_rejects_unknown_scope(workspace):
    ok, message = create_skill("ok-name", scope="everyone")

    assert ok is False and "无效作用域" in message


def test_create_skill_does_not_overwrite_existing(workspace):
    create_skill("dup", scope="project")

    ok, message = create_skill("dup", scope="project")

    assert ok is False and "已存在" in message


def test_created_skill_is_loadable_end_to_end(workspace):
    create_skill("round-trip", scope="project")

    loaded = load_skill("round-trip")

    assert "[已加载 skill: round-trip（project）]" in loaded


# ===== 目录设置 =====

def test_set_skills_dir_normalises_and_round_trips(tmp_path):
    original = get_skills_dir()

    resolved = set_skills_dir(str(tmp_path / "skills"))

    assert resolved == str(tmp_path / "skills")
    assert get_skills_dir() == resolved
    set_skills_dir(original)


# ===== 注入给模型的工具描述 =====

def test_skill_descriptions_are_injected_into_the_tool_schema(workspace):
    """模型只能靠 description 判断"何时该加载"，所以这份清单必须进 schema。"""
    workspace.add_skill("tdd", FM.format(name="tdd"))
    workspace.add_skill("plain", "没有 frontmatter")

    from zzhclaw.coding.tools import get_tools_with_cwd

    description = next(t["function"]["description"] for t in get_tools_with_cwd()
                       if t["function"]["name"] == "Skill")

    assert "tdd [project]: 需要改动前先跑测试" in description
    assert "plain [project]: （无描述）" in description


def test_empty_skill_listing_tells_the_model_where_it_looked(workspace):
    from zzhclaw.coding.tools import get_tools_with_cwd

    description = next(t["function"]["description"] for t in get_tools_with_cwd()
                       if t["function"]["name"] == "Skill")

    assert "当前无可用 skill" in description
    assert str(workspace.cwd / ".zzhclaw" / "skills") in description
