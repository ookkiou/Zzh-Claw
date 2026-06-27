"""
zzhclaw.tools - 内置工具定义
"""

from .registry import (
    TOOLS,
    execute_tool,
    read_file,
    write_file,
    run_bash,
    web_search,
    fetch_webpage
)

__all__ = [
    "TOOLS",
    "execute_tool",
    "read_file",
    "write_file",
    "run_bash",
    "web_search",
    "fetch_webpage"
]
