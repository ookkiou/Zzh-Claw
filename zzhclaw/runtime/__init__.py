"""工具和评测共用的本地执行基础设施。"""

from .commands import CommandResult, command_environment, run_command
from .results import ToolResult

__all__ = ["CommandResult", "ToolResult", "command_environment", "run_command"]
