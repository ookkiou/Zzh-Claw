"""
zzhclaw.tools - 工具定义
"""

import os
import re
import json
import time
import fnmatch
import glob
import subprocess
import threading
import fcntl
from contextlib import contextmanager
from typing import Dict, Any, List, Optional

try:
    from ddgs import DDGS
    HAS_DDGS = True
except ImportError:
    HAS_DDGS = False

try:
    import requests
    from bs4 import BeautifulSoup
    HAS_WEB = True
except ImportError:
    HAS_WEB = False


# ===== 危险命令黑名单 =====
# 命中任一则 run_bash 直接拒绝执行（不依赖用户确认，避免习惯性按 Y）。
# 设计原则：只拦截"针对系统关键路径的破坏"和"远程代码直接执行"，
# 不拦截项目目录内的正常 rm/mv 等操作。
_DANGEROUS_PATTERNS = [
    # rm -rf 系统关键路径：单独的 / 后面必须是分隔符或 *；~/$HOME/系统目录后允许跟 / 继续路径
    (r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)[a-zA-Z]*\s+"
     r"(/(?=\s|$|;|&&|\||\*)"
     r"|~(?=/|\s|$|;|&&|\|)"
     r"|\$HOME(?=/|\s|$|;|&&|\|)"
     r"|/(etc|usr|var|bin|sbin|opt|System|Library|Applications|dev|proc|sys)(?=/|\s|$|;|&&|\|))",
     "rm -rf 系统关键路径"),
    (r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*\s+/(?=\s|$|;|&&|\*)",
     "rm -r 根目录"),
    (r"\bsudo\s+rm\s+-[a-zA-Z]*r[a-zA-Z]*f|\bsudo\s+rm\s+-[a-zA-Z]*f[a-zA-Z]*r",
     "sudo rm -rf"),
    # 格式化 / 写块设备
    (r"\bmkfs(\.\w+)?\b", "格式化磁盘"),
    (r"\bdd\s+[^|]*\bof=/dev/(sd|nvme|hd|disk|rdisk)", "dd 写入块设备"),
    (r">\s*/dev/(sd|nvme|hd|disk|rdisk)", "覆写块设备"),
    # 关机 / 重启
    (r"\b(shutdown|reboot|halt|poweroff)\b", "关机/重启"),
    # fork 炸弹
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "fork 炸弹"),
    # 全局权限修改
    (r"\bchmod\s+(-[a-zA-Z]*R[a-zA-Z]*\s+)?777\s+/(\s|$|;|&&)", "全局 chmod 777 /"),
    (r"\bchown\s+-[a-zA-Z]*R[a-zA-Z]*\s+\S+\s+/(\s|$|;|&&)", "全局 chown /"),
    # 远程脚本直接执行
    (r"\b(curl|wget|fetch)\b[^|]*\|\s*(sudo\s+)?(ba|z|k|da)?sh\b", "远程脚本管道到 shell 执行"),
    # macOS 特有：关闭 SIP、删除系统完整性文件
    (r"\bcsrutil\s+disable\b", "关闭 macOS SIP"),
    # 历史清空 / 权限自杀
    (r"\bhistory\s+-c\b.*&&.*\brm\b", "清空历史并删除"),
]

_DANGEROUS_REGEX = [(re.compile(p, re.IGNORECASE), desc) for p, desc in _DANGEROUS_PATTERNS]


def check_dangerous_command(command: str) -> Optional[str]:
    """检查命令是否命中危险模式，返回描述，安全则返回 None"""
    for regex, desc in _DANGEROUS_REGEX:
        if regex.search(command):
            return desc
    return None


# ===== 工作目录管理 =====
# 使用 threading.local 隔离每个 Agent 线程的工作目录，支持多任务并发。
_local = threading.local()


def _get_workspace() -> Dict[str, Any]:
    """获取当前线程的工作区配置（懒初始化）"""
    if not hasattr(_local, "workspace"):
        _local.workspace = {"cwd": os.getcwd(), "sandbox": True}
    return _local.workspace


# 向后兼容：保留 _WORKSPACE 名称供内部使用，实际代理到线程局部存储
class _WorkspaceProxy:
    def __getitem__(self, key):
        return _get_workspace()[key]
    def __setitem__(self, key, value):
        _get_workspace()[key] = value
    def get(self, key, default=None):
        return _get_workspace().get(key, default)

_WORKSPACE = _WorkspaceProxy()

# ===== Skill 目录 =====
# 约定：<skills_dir>/<name>/SKILL.md，每个 SKILL.md 可带 YAML frontmatter（name/description）。
# 两级作用域：
#   - 项目级：<cwd>/.zzhclaw/skills（随仓库版本控制、团队共享，优先级更高）
#   - 全局级：~/.zzhclaw/skills（个人跨项目，可用 set_skills_dir 覆盖）
_GLOBAL_SKILLS_DIR = os.path.expanduser("~/.zzhclaw/skills")
_PROJECT_SKILLS_SUBDIR = os.path.join(".zzhclaw", "skills")

# 向后兼容旧名（指向全局目录）
_SKILLS_DIR = _GLOBAL_SKILLS_DIR


def set_skills_dir(path: str) -> str:
    """设置全局 skill 根目录，返回规范化绝对路径"""
    global _GLOBAL_SKILLS_DIR, _SKILLS_DIR
    _GLOBAL_SKILLS_DIR = os.path.abspath(os.path.expanduser(path))
    _SKILLS_DIR = _GLOBAL_SKILLS_DIR
    return _GLOBAL_SKILLS_DIR


def get_skills_dir() -> str:
    """获取全局 skill 根目录（向后兼容）"""
    return _GLOBAL_SKILLS_DIR


def get_skills_dirs() -> List[Dict[str, str]]:
    """返回按优先级排序的 skill 目录：[{scope, path}]，项目级在前。

    项目级目录基于当前工作目录（get_cwd()）动态推导，因此 /cd 后自动跟随。
    """
    return [
        {"scope": "project", "path": os.path.join(get_cwd(), _PROJECT_SKILLS_SUBDIR)},
        {"scope": "global", "path": _GLOBAL_SKILLS_DIR},
    ]

# 搜索时跳过的目录（grep/glob 用）
_IGNORE_DIRS = {
    ".git", ".venv", ".venv-1", "venv", "env", "ENV",
    "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".idea", ".vscode", ".trae", "dist", "build", ".eggs",
}


# ===== 工具风险分类（权限模式用）=====
# 只读工具：无副作用，smart 模式下自动批准
READONLY_TOOLS = {"read_file", "grep_files", "glob_files", "web_search", "fetch_webpage", "Skill"}
# 写/执行工具：有副作用，smart 模式下仍需确认
WRITE_TOOLS = {"write_file", "edit_file", "run_bash"}


def is_readonly_tool(name: str) -> bool:
    """判断工具是否只读（无副作用）"""
    return name in READONLY_TOOLS


def set_cwd(path: str) -> str:
    """设置工作目录，返回规范化绝对路径或错误信息"""
    abs_path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(abs_path):
        return f"错误: 目录不存在: {abs_path}"
    _WORKSPACE["cwd"] = abs_path
    return abs_path


def get_cwd() -> str:
    """获取当前工作目录"""
    return _WORKSPACE["cwd"]


def set_sandbox(enabled: bool) -> None:
    """开关 write_file 沙箱（限制写入 cwd 内）"""
    _WORKSPACE["sandbox"] = enabled


def get_sandbox() -> bool:
    """返回当前线程的写沙箱状态。"""
    return bool(_WORKSPACE.get("sandbox", True))


def _resolve_path(path: str) -> str:
    """解析路径：相对路径基于 cwd，绝对路径规范化"""
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(_WORKSPACE["cwd"], path))


def _check_write_sandbox(resolved_path: str) -> Optional[str]:
    """写沙箱检查：路径必须在 cwd 内。返回错误信息或 None（放行）"""
    if not _WORKSPACE["sandbox"]:
        return None
    real_target = os.path.realpath(resolved_path)
    real_cwd = os.path.realpath(_WORKSPACE["cwd"])
    if not (real_target == real_cwd or real_target.startswith(real_cwd + os.sep)):
        return (
            f"错误: 写入被沙箱拒绝。目标 {resolved_path} 不在工作目录 {_WORKSPACE['cwd']} 内。\n"
            "如需写入外部路径，请用 /sandbox off 关闭沙箱（谨慎）。"
        )
    return None


def get_tools_with_cwd() -> List[Dict[str, Any]]:
    """返回工具列表，描述里动态注入当前工作目录（让模型知道相对路径基准）"""
    cwd = _WORKSPACE["cwd"]
    sandbox_note = "（写沙箱已启用，只能写工作目录内）" if _WORKSPACE["sandbox"] else "（写沙箱已关闭）"
    tools = []
    for tool in TOOLS:
        t = json.loads(json.dumps(tool))  # 深拷贝，避免污染原 TOOLS
        name = t["function"]["name"]
        if name == "read_file":
            t["function"]["description"] += f"\n当前工作目录: {cwd}（相对路径基于此解析）"
        elif name == "write_file":
            t["function"]["description"] += f"\n当前工作目录: {cwd}（相对路径基于此解析）{sandbox_note}"
        elif name == "run_bash":
            t["function"]["description"] += f"\n命令在工作目录下执行: {cwd}"
        elif name == "Skill":
            skills = list_skills()
            if skills:
                # 关键：把每个 skill 的 description 也注入，模型才能判断何时该加载
                lines = "\n".join(
                    f"  - {s['name']} [{s['scope']}]: {s['description'] or '（无描述）'}" for s in skills
                )
                t["function"]["description"] += (
                    "\n当前可用 skill（名称 [作用域]: 何时使用）:\n" + lines
                )
            else:
                dirs = "、".join(d["path"] for d in get_skills_dirs())
                t["function"]["description"] += f"\n当前无可用 skill（已扫描: {dirs}）"
        tools.append(t)
    return tools


# 工具定义
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文件内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入文件内容（覆盖现有文件）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径"
                    },
                    "content": {
                        "type": "string",
                        "description": "文件内容"
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "增量编辑文件：用 new_text 精确替换 old_text。\n"
                "适用于修改现有文件的部分内容，比 write_file 全量覆写更省 token、更安全。\n"
                "要求：old_text 必须与文件内容精确匹配（含空格/缩进/换行），且默认必须唯一。\n"
                "若匹配多处，请提供更多上下文使其唯一，或设 replace_all=true 替换全部。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径（相对路径基于工作目录）"
                    },
                    "old_text": {
                        "type": "string",
                        "description": "要被替换的原文本（必须精确匹配）"
                    },
                    "new_text": {
                        "type": "string",
                        "description": "替换后的新文本"
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": "是否替换所有匹配（默认 false，要求唯一匹配）",
                        "default": False
                    }
                },
                "required": ["path", "old_text", "new_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_bash",
            "description": (
                "运行 bash 命令（带安全策略）\n"
                "以下行为会被拒绝：rm -rf 系统目录、mkfs、dd of=/dev/*、"
                "shutdown/reboot、fork 炸弹、chmod/chown -R /、curl|sh 等。\n"
                "若确需执行，请提示用户手动在终端运行。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要运行的命令"
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "联网搜索（用 DuckDuckGo）",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词"
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "返回结果数量（默认 5）",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_webpage",
            "description": "获取网页内容并提取文本",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "网页 URL"
                    },
                    "max_length": {
                        "type": "integer",
                        "description": "最大文本长度（默认 10000）",
                        "default": 10000
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "grep_files",
            "description": (
                "在文件内容里搜索匹配正则表达式的行（类似 grep -rn）。\n"
                "自动跳过 .git/.venv/node_modules/__pycache__ 等目录。\n"
                "返回格式：相对路径:行号: 匹配行内容"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "搜索模式（正则表达式）"
                    },
                    "path": {
                        "type": "string",
                        "description": "搜索起始路径（默认工作目录）",
                        "default": "."
                    },
                    "include": {
                        "type": "string",
                        "description": "文件名 glob 过滤（如 *.py），可选"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大结果数（默认 50）",
                        "default": 50
                    },
                    "ignore_case": {
                        "type": "boolean",
                        "description": "是否忽略大小写（默认 false）",
                        "default": False
                    }
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "glob_files",
            "description": (
                "按 glob 模式查找文件路径（类似 find，支持 ** 递归）。\n"
                "自动跳过 .git/.venv/node_modules 等目录。\n"
                "返回相对工作目录的文件路径列表。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "glob 模式（如 **/*.py, src/*.js, *.md）"
                    },
                    "path": {
                        "type": "string",
                        "description": "搜索起始路径（默认工作目录）",
                        "default": "."
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大结果数（默认 100）",
                        "default": 100
                    }
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Skill",
            "description": (
                "加载一个可用的 skill（专业技能指令）。\n"
                "不传 name：返回所有可用 skill 的清单（名称+描述）；\n"
                "传入 name：返回该 skill 的完整指令正文，读取后应遵循其中步骤完成任务。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "要加载的 skill 名称；省略或传 'list' 则列出全部可用 skill"
                    }
                },
                "required": []
            }
        }
    }
]


@contextmanager
def _file_lock(path: str, timeout: float = 10.0):
    """对文件加排他锁，防止多 Agent 并发写时发生 lost-update。

    使用 <path>.lock 旁路锁文件（不锁原文件，避免 write 模式截断时死锁）。
    锁文件本身不删除——删除会产生新的竞态；*.lock 应加入 .gitignore。
    timeout: 等待锁的最大秒数，超时则抛出 TimeoutError。
    """
    lock_path = path + ".lock"
    lock_fd = open(lock_path, "w")
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"等待文件锁超时（{timeout}s）: {path}")
                time.sleep(0.05)
        yield
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            lock_fd.close()


def read_file(path: str) -> str:
    """读取文件（相对路径基于工作目录解析）"""
    resolved = _resolve_path(path)
    try:
        with open(resolved, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"错误: {e}"


def write_file(path: str, content: str) -> str:
    """写入文件（相对路径基于工作目录解析，带写沙箱和文件锁）"""
    resolved = _resolve_path(path)
    sandbox_err = _check_write_sandbox(resolved)
    if sandbox_err:
        return sandbox_err
    try:
        parent = os.path.dirname(resolved)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with _file_lock(resolved):
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(content)
        return f"成功写入: {resolved}"
    except TimeoutError as e:
        return f"错误: {e}（另一个任务正在写该文件，请稍后重试）"
    except Exception as e:
        return f"错误: {e}"


def edit_file(path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
    """增量编辑文件：用 new_text 精确替换 old_text（带写沙箱和文件锁）

    整个 read-modify-write 过程持有排他锁，防止并发 Agent 发生 lost-update。
    """
    resolved = _resolve_path(path)
    sandbox_err = _check_write_sandbox(resolved)
    if sandbox_err:
        return sandbox_err

    if old_text == new_text:
        return "错误: old_text 和 new_text 相同，无需修改"

    try:
        with _file_lock(resolved):
            # 读取原文件（持锁，确保读到的是最新内容）
            try:
                with open(resolved, "r", encoding="utf-8") as f:
                    content = f.read()
            except FileNotFoundError:
                return f"错误: 文件不存在: {resolved}"
            except Exception as e:
                return f"错误: 读取文件失败: {e}"

            # 匹配检查
            count = content.count(old_text)
            if count == 0:
                return (
                    f"错误: 未找到要替换的文本。\n"
                    "请确保 old_text 与文件内容精确匹配（包括空格、缩进、换行符）。\n"
                    "提示：可先用 read_file 查看文件实际内容，复制精确片段。"
                )
            if count > 1 and not replace_all:
                return (
                    f"错误: 找到 {count} 处匹配，old_text 不唯一。\n"
                    f"请提供更多上下文使其唯一，或设 replace_all=true 替换全部 {count} 处。"
                )

            # 执行替换
            if replace_all:
                new_content = content.replace(old_text, new_text)
                replaced = count
            else:
                new_content = content.replace(old_text, new_text, 1)
                replaced = 1

            # 写回（仍持锁）
            try:
                with open(resolved, "w", encoding="utf-8") as f:
                    f.write(new_content)
            except Exception as e:
                return f"错误: 写入失败: {e}"

        return f"成功编辑: {resolved}（替换 {replaced} 处）"
    except TimeoutError as e:
        return f"错误: {e}（另一个任务正在编辑该文件，请稍后重试）"


def run_bash(command: str) -> str:
    """运行 bash 命令（带危险命令拦截）"""
    # 安全策略：命中黑名单直接拒绝，不给用户误按 Y 的机会
    danger = check_dangerous_command(command)
    if danger:
        return (
            f"错误: 命令被安全策略拒绝执行（命中：{danger}）。\n"
            f"原始命令：{command}\n"
            "如确需执行，请提示用户手动在终端运行，或拆分为更安全的子命令。"
        )
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=_WORKSPACE["cwd"],
        )
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        if result.returncode != 0:
            output += f"\n(退出码: {result.returncode})"
        return output or "(无输出)"
    except subprocess.TimeoutExpired:
        return "错误: 命令超时 (30秒)"
    except Exception as e:
        return f"错误: {e}"


def web_search(query: str, num_results: int = 5) -> str:
    """联网搜索"""
    if not HAS_DDGS:
        return "错误: 未安装 ddgs，请运行: pip3 install ddgs"
    try:
        # bing backend 对中文最稳定;失败则回退 duckduckgo
        try:
            results = DDGS().text(query, max_results=num_results, backend="bing")
        except Exception:
            results = DDGS().text(query, max_results=num_results, backend="duckduckgo")
        if not results:
            return "无搜索结果"
        output = f"搜索结果: {query}\n\n"
        for i, r in enumerate(results, 1):
            output += f"[{i}] {r.get('title', '无标题')}\n"
            output += f"    {r.get('href', '无链接')}\n"
            output += f"    {r.get('body', '无摘要')}\n\n"
        return output
    except Exception as e:
        return f"搜索错误: {e}"


def fetch_webpage(url: str, max_length: int = 10000) -> str:
    """获取网页内容"""
    if not HAS_WEB:
        return "错误: 未安装 requests/beautifulsoup4，请运行: pip3 install requests beautifulsoup4"
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        # 提取文本
        for script in soup(["script", "style"]):
            script.decompose()
        text = soup.get_text(separator="\n", strip=True)
        # 清理多余空行
        lines = [line.strip() for line in text.splitlines()]
        text = "\n".join(line for line in lines if line)
        # 截断
        if len(text) > max_length:
            text = text[:max_length] + f"\n\n(已截断，超过 {max_length} 字符)"
        return f"网页: {url}\n\n{text}"
    except Exception as e:
        return f"获取网页错误: {e}"


def grep_files(pattern: str, path: str = ".", include: Optional[str] = None,
               max_results: int = 50, ignore_case: bool = False) -> str:
    """在文件内容里搜索匹配正则的行（类似 grep -rn）"""
    search_root = _resolve_path(path)
    if not os.path.isdir(search_root):
        return f"错误: 目录不存在: {search_root}"

    flags = re.IGNORECASE if ignore_case else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return f"错误: 无效的正则表达式: {e}"

    matches: List[str] = []
    files_scanned = 0
    for root, dirs, files in os.walk(search_root):
        # 原地修改 dirs 跳过忽略目录（影响 os.walk 后续遍历）
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.endswith(".egg-info")]
        for fname in files:
            if include and not fnmatch.fnmatch(fname, include):
                continue
            fpath = os.path.join(root, fname)
            files_scanned += 1
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    for lineno, line in enumerate(f, 1):
                        if regex.search(line):
                            rel = os.path.relpath(fpath, search_root)
                            matches.append(f"{rel}:{lineno}: {line.rstrip()}")
                            if len(matches) >= max_results:
                                break
            except OSError:
                continue  # 跳过无权限/特殊文件
            if len(matches) >= max_results:
                break
        if len(matches) >= max_results:
            break

    if not matches:
        return f"未找到匹配: {pattern}（扫描了 {files_scanned} 个文件）"

    header = f"找到 {len(matches)} 处匹配（模式: {pattern}）:\n\n"
    return header + "\n".join(matches)


def glob_files(pattern: str, path: str = ".", max_results: int = 100) -> str:
    """按 glob 模式查找文件路径（支持 ** 递归）"""
    search_root = _resolve_path(path)
    if not os.path.isdir(search_root):
        return f"错误: 目录不存在: {search_root}"

    full_pattern = os.path.join(search_root, pattern)
    try:
        results = glob.glob(full_pattern, recursive=True)
    except Exception as e:
        return f"错误: glob 失败: {e}"

    # 过滤忽略目录里的结果，转为相对路径
    filtered: List[str] = []
    for r in results:
        rel = os.path.relpath(r, search_root)
        parts = rel.split(os.sep)
        if any(p in _IGNORE_DIRS or p.endswith(".egg-info") for p in parts):
            continue
        filtered.append(rel)
        if len(filtered) >= max_results:
            break

    if not filtered:
        return f"未找到匹配文件: {pattern}"

    filtered.sort()
    header = f"找到 {len(filtered)} 个文件（模式: {pattern}）:\n\n"
    return header + "\n".join(filtered)


def _parse_frontmatter(text: str):
    """轻量解析 SKILL.md 的 YAML frontmatter（仅支持 key: value 单行）。

    返回 (meta: dict, body: str)。无 frontmatter 时 meta 为空、body 为原文。
    """
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        close_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                close_idx = i
                break
        if close_idx is not None:
            meta: Dict[str, str] = {}
            for line in lines[1:close_idx]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip().strip("\"'")
            body = "\n".join(lines[close_idx + 1:]).lstrip("\n")
            return meta, body
    return {}, text


def list_skills() -> List[Dict[str, str]]:
    """扫描项目级 + 全局级 skill 目录，返回 [{name, description, dir, scope, path}]。

    同名 skill 项目级优先（覆盖全局级）；目录不存在则跳过。
    """
    result: List[Dict[str, str]] = []
    seen = set()
    for d in get_skills_dirs():  # 项目级在前，先加入者胜出
        scope, base = d["scope"], d["path"]
        if not os.path.isdir(base):
            continue
        for entry in sorted(os.listdir(base)):
            skill_path = os.path.join(base, entry, "SKILL.md")
            if not os.path.isfile(skill_path):
                continue
            try:
                with open(skill_path, "r", encoding="utf-8") as f:
                    meta, _ = _parse_frontmatter(f.read())
            except Exception:
                meta = {}
            name = meta.get("name", entry)
            if name in seen:
                continue  # 已被更高优先级作用域占用
            seen.add(name)
            result.append({
                "name": name,
                "description": meta.get("description", ""),
                "dir": entry,
                "scope": scope,
                "path": skill_path,
            })
    return result


def load_skill(name: str) -> str:
    """读取指定 skill 的 SKILL.md（项目级优先），返回带标题的指令正文（含目录穿越防护）。"""
    safe = os.path.basename(name)  # 防 ../ 目录穿越

    # 1. 优先按 list_skills 结果匹配（尊重 name 字段与作用域优先级）
    target_path = None
    target_scope = None
    for s in list_skills():
        if s["name"] == safe or s["dir"] == safe:
            target_path = s["path"]
            target_scope = s["scope"]
            break

    # 2. 兜底：直接按目录名在各作用域下找
    if target_path is None:
        for d in get_skills_dirs():
            candidate = os.path.join(d["path"], safe, "SKILL.md")
            if os.path.isfile(candidate):
                target_path = candidate
                target_scope = d["scope"]
                break

    if target_path is None:
        avail = ", ".join(s["name"] for s in list_skills()) or "（无）"
        return f"错误: 未找到 skill '{name}'。可用 skill: {avail}"

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return f"错误: 读取 skill 失败: {e}"
    meta, body = _parse_frontmatter(content)
    header = f"[已加载 skill: {meta.get('name', safe)}（{target_scope}）]\n"
    if meta.get("description"):
        header += f"描述: {meta['description']}\n"
    header += "\n请按以下指令执行：\n\n"
    return header + body


def skill_tool(name: Optional[str] = None) -> str:
    """Skill 工具入口：无 name → 列出全部；有 name → 加载该 skill。"""
    if not name or name.strip().lower() in ("list", "ls", ""):
        skills = list_skills()
        if not skills:
            dirs = "、".join(f"{d['scope']}({d['path']})" for d in get_skills_dirs())
            return (
                f"当前没有可用的 skill。已扫描目录：{dirs}。\n"
                "每个 skill 形如 <目录>/<name>/SKILL.md。"
            )
        out = "可用的 skill：\n\n"
        for s in skills:
            out += f"- [{s['scope']}] {s['name']}: {s['description'] or '（无描述）'}\n"
        out += "\n使用方式：再次调用 Skill 工具并传入 name 加载具体指令。"
        return out
    return load_skill(name)


_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def create_skill(name: str, scope: str = "project") -> tuple:
    """在指定作用域创建 skill 模板。返回 (ok: bool, message: str)。

    scope: project → <cwd>/.zzhclaw/skills/<name>；global → ~/.zzhclaw/skills/<name>
    """
    name = (name or "").strip()
    if not name:
        return False, "错误: skill 名称不能为空"
    if not _SKILL_NAME_RE.match(name):
        return False, f"错误: skill 名称只能含字母/数字/-/_，收到 '{name}'"
    if scope not in ("project", "global"):
        return False, f"错误: 无效作用域 '{scope}'（可选 project|global）"

    base = os.path.join(get_cwd(), _PROJECT_SKILLS_SUBDIR) if scope == "project" else _GLOBAL_SKILLS_DIR
    skill_dir = os.path.join(base, name)
    skill_path = os.path.join(skill_dir, "SKILL.md")
    if os.path.exists(skill_path):
        return False, f"错误: skill 已存在: {skill_path}"
    try:
        os.makedirs(skill_dir, exist_ok=True)
        template = (
            "---\n"
            f"name: {name}\n"
            'description: 写清楚“何时该用这个 skill”的触发条件，模型据此决定是否加载\n'
            "---\n"
            f"# {name} Skill\n\n"
            "在此写 skill 的具体指令步骤。\n"
        )
        with open(skill_path, "w", encoding="utf-8") as f:
            f.write(template)
    except Exception as e:
        return False, f"错误: 创建失败: {e}"
    return True, (
        f"已创建 {scope} skill: {skill_path}\n"
        "请编辑该文件的 description（触发条件）和正文（指令）。"
    )


def execute_tool(name: str, args: Dict[str, Any]) -> str:
    """执行工具"""
    if name == "read_file":
        return read_file(args["path"])
    elif name == "write_file":
        return write_file(args["path"], args["content"])
    elif name == "edit_file":
        return edit_file(
            args["path"],
            args["old_text"],
            args["new_text"],
            args.get("replace_all", False),
        )
    elif name == "run_bash":
        return run_bash(args["command"])
    elif name == "web_search":
        return web_search(args["query"], args.get("num_results", 5))
    elif name == "fetch_webpage":
        return fetch_webpage(args["url"], args.get("max_length", 10000))
    elif name == "grep_files":
        return grep_files(
            args["pattern"],
            args.get("path", "."),
            args.get("include"),
            args.get("max_results", 50),
            args.get("ignore_case", False),
        )
    elif name == "glob_files":
        return glob_files(
            args["pattern"],
            args.get("path", "."),
            args.get("max_results", 100),
        )
    elif name == "Skill":
        return skill_tool(args.get("name"))
    else:
        return f"未知工具: {name}"
