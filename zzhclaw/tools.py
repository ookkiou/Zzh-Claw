"""
tools.py - 工具定义 (对应 coding-agent 的工具)
"""

import os
import json
import subprocess
from typing import Dict, Any, List

try:
    from duckduckgo_search import DDGS
    HAS_DDGS = True
except ImportError:
    HAS_DDGS = False

try:
    import requests
    from bs4 import BeautifulSoup
    HAS_WEB = True
except ImportError:
    HAS_WEB = False

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
            "name": "run_bash",
            "description": "运行 bash 命令",
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
    }
]


def read_file(path: str) -> str:
    """读取文件"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"错误: {e}"


def write_file(path: str, content: str) -> str:
    """写入文件"""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"成功写入: {path}"
    except Exception as e:
        return f"错误: {e}"


def run_bash(command: str) -> str:
    """运行 bash 命令"""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
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
        return "错误: 未安装 duckduckgo-search，请运行: pip3 install duckduckgo-search"
    try:
        results = DDGS().text(query, max_results=num_results)
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


def execute_tool(name: str, args: Dict[str, Any]) -> str:
    """执行工具"""
    if name == "read_file":
        return read_file(args["path"])
    elif name == "write_file":
        return write_file(args["path"], args["content"])
    elif name == "run_bash":
        return run_bash(args["command"])
    elif name == "web_search":
        return web_search(args["query"], args.get("num_results", 5))
    elif name == "fetch_webpage":
        return fetch_webpage(args["url"], args.get("max_length", 10000))
    else:
        return f"未知工具: {name}"
