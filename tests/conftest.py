"""pytest 全局夹具。

三条隔离保证：
1. 凭据不进测试进程（即使 .env 存在也读不到真实 key）；
2. 真实网络被拦截（除非显式打 network / llm 标记）；
3. 每个测试有独立的工作目录与 skill 目录，不碰仓库真实文件。
"""

import os
import socket

import pytest


_CREDENTIAL_PREFIXES = ("OPENAI_", "ANTHROPIC_", "AZURE_OPENAI_")


def pytest_addoption(parser):
    parser.addoption(
        "--run-llm",
        action="store_true",
        default=False,
        help="运行标记为 llm 的真实 API 冒烟测试（会产生费用）",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-llm"):
        return
    skip = pytest.mark.skip(reason="需要 --run-llm 且真实 API key")
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _no_llm_credentials(monkeypatch):
    """抹掉所有 LLM 凭据相关环境变量。

    zzhclaw.ai.client 在 import 时执行 load_dotenv()，会把 .env 里的真实 key 灌进
    os.environ；本夹具在每个测试前清除，因此任何测试意外构造真实 LLMClient 会立刻
    ValueError，而不是静默发出计费请求。
    """
    for key in list(os.environ):
        if key.startswith(_CREDENTIAL_PREFIXES):
            monkeypatch.delenv(key, raising=False)
    yield


@pytest.fixture(autouse=True)
def _block_real_network(request, monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError(
            "测试试图解析/连接真实网络。请改用 FakeLLM 或 mock；"
            "确需网络的用例请标记 @pytest.mark.network 或 @pytest.mark.llm"
        )

    if request.node.get_closest_marker("network") or request.node.get_closest_marker("llm"):
        return

    monkeypatch.setattr(socket, "getaddrinfo", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


@pytest.fixture(autouse=True)
def workspace(tmp_path):
    """把工具层的工作区指向本测试专属的 tmp_path。

    registry 用 threading.local 存 cwd（默认是进程启动目录）且写沙箱默认开启，
    不重定向的话：相对路径会解析到仓库根目录，且 tmp_path 会被沙箱判为越界。
    """
    from zzhclaw.coding.tools import registry

    prev_cwd = registry.get_cwd()
    prev_sandbox = registry._WORKSPACE.get("sandbox", True)
    prev_skills = registry.get_skills_dir()

    project_skills_root = tmp_path / "cwd"
    project_skills_root.mkdir()
    global_skills = tmp_path / "global-skills"

    registry.set_cwd(str(project_skills_root))
    registry.set_sandbox(True)
    registry.set_skills_dir(str(global_skills))

    yield Workspace(project_skills_root, global_skills)

    registry.set_cwd(prev_cwd)
    registry.set_sandbox(prev_sandbox)
    registry.set_skills_dir(prev_skills)


class Workspace:
    """当前测试的工作区路径，供用例构造文件。"""

    def __init__(self, cwd, global_skills_dir):
        self.cwd = cwd
        self.global_skills_dir = global_skills_dir

    def write(self, rel_path: str, content: str = "") -> str:
        """在沙箱内直接落一个文件（绕过被测代码），返回相对路径。"""
        target = self.cwd / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return rel_path

    def add_skill(self, dir_name: str, frontmatter: str = "", body: str = "指令正文", scope: str = "project"):
        base = self.cwd / ".zzhclaw" / "skills" if scope == "project" else self.global_skills_dir
        skill_dir = base / dir_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"{frontmatter}{body}", encoding="utf-8")
        return skill_dir / "SKILL.md"


@pytest.fixture
def session_manager(tmp_path):
    """会话存储指向 tmp_path，绝不读写 ~/.zzhclaw/sessions。"""
    from zzhclaw.coding.session import SessionManager

    return SessionManager(storage_dir=str(tmp_path / "sessions"))


@pytest.fixture
def make_agent(session_manager):
    """构造接上 FakeLLM 与隔离会话的 Agent；脚本项交给 FakeLLM 解释。"""
    from fake_llm import FakeLLM
    from zzhclaw.agent import Agent

    def _make(script=(), llm=None, **kwargs):
        return Agent(
            llm=llm or FakeLLM(script),
            session_manager=session_manager,
            **kwargs,
        )

    return _make


class ToolStub:
    """替代 core.execute_tool 的工具桩：记录调用、返回预设结果、可模拟抛异常。"""

    def __init__(self):
        self.calls = []
        self.results = {}
        self.raises = {}
        self.default = None

    def __call__(self, name, args):
        self.calls.append((name, args))
        if name in self.raises:
            raise self.raises[name]
        if name in self.results:
            return self.results[name]
        return self.default if self.default is not None else f"[stub] {name} 已执行"


@pytest.fixture
def stub_tools(monkeypatch):
    """Agent 循环测试专用：不碰真实文件系统/网络，只验证编排逻辑。

    注意要打的是 zzhclaw.agent.core 里的名字（core.py 用 from-import 绑定了它），
    patch registry 上的 execute_tool 不会生效。
    """
    import zzhclaw.agent.core as agent_core

    stub = ToolStub()
    monkeypatch.setattr(agent_core, "execute_tool", stub)
    return stub
