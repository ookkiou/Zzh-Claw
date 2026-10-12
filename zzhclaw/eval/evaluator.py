"""在 Agent 工作区之外执行确定性验收命令。"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict

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


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


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
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                cwd=self.benchmark_root,
                env=self._environment(task, workspace_path),
                capture_output=True,
                text=True,
                timeout=task.validator.timeout_seconds,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            return ValidatorResult(
                exit_code=None,
                timed_out=True,
                stdout=_text(exc.stdout)[: self.output_limit],
                stderr=_text(exc.stderr)[: self.output_limit],
                duration_ms=duration_ms,
            )
        except OSError as exc:
            raise ValidatorExecutionError(
                f"无法启动 validator 命令 {command!r}: {type(exc).__name__}: {exc}"
            ) from exc

        duration_ms = int((time.perf_counter() - started) * 1000)
        return ValidatorResult(
            exit_code=completed.returncode,
            timed_out=False,
            stdout=completed.stdout[: self.output_limit],
            stderr=completed.stderr[: self.output_limit],
            duration_ms=duration_ms,
        )
