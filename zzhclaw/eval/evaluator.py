"""在 Agent 工作区之外执行确定性验收命令。"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict

from zzhclaw.runtime import run_command

from .models import EvalTask, ValidatorResult

_ENV_ALLOWLIST = {
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "VIRTUAL_ENV",
    "WINDIR",
}


class ValidatorExecutionError(RuntimeError):
    """验收进程无法启动或无法正常收集结果。"""


class ExternalValidator:
    def __init__(self, benchmark_root: str | Path, *, output_limit: int = 100_000):
        self.benchmark_root = Path(benchmark_root).resolve()
        if not self.benchmark_root.is_dir():
            raise ValueError(f"benchmark_root 不存在或不是目录: {self.benchmark_root}")
        if output_limit <= 0:
            raise ValueError("output_limit 必须是正整数")
        self.output_limit = output_limit

    def _expand(self, value: str, workspace: Path) -> str:
        return value.replace("{workspace}", str(workspace)).replace(
            "{python}", sys.executable
        )

    def _environment(self, task: EvalTask, workspace: Path) -> Dict[str, str]:
        env = {key: value for key, value in os.environ.items() if key in _ENV_ALLOWLIST}
        env["PYTHONNOUSERSITE"] = "1"
        for key, value in task.validator.env.items():
            env[key] = self._expand(value, workspace)
        return env

    def run(self, task: EvalTask, workspace: str | Path) -> ValidatorResult:
        workspace_path = Path(workspace).resolve()
        if not workspace_path.is_dir():
            raise ValidatorExecutionError(
                f"任务工作区不存在或不是目录: {workspace_path}"
            )
        command = [
            self._expand(part, workspace_path) for part in task.validator.command
        ]
        result = run_command(
            command,
            cwd=self.benchmark_root,
            env=self._environment(task, workspace_path),
            timeout=task.validator.timeout_seconds,
            output_limit=self.output_limit,
        )
        if result.status == "capture_error":
            raise ValidatorExecutionError("validator 输出收集失败，不能判定任务通过")
        if result.status == "spawn_error":
            raise ValidatorExecutionError(f"无法启动 validator 命令: {result.error}")
        return ValidatorResult(
            exit_code=result.exit_code,
            timed_out=result.status == "timeout",
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=result.duration_ms,
            stdout_truncated=result.stdout_truncated,
            stderr_truncated=result.stderr_truncated,
            error_code=result.error_code,
        )
