"""为每个评测任务创建可清理的独立工作副本。"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .models import EvalTask
from .task_loader import LoadedBenchmark


class WorkspaceError(RuntimeError):
    """任务工作区无法安全创建或清理。"""


def _safe_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    return normalized[:64] or "task"


def _reject_symlinks(root: Path) -> None:
    """v0.1 fixture 不接受软链接，避免复制时意外读取目录外内容。"""
    for path in root.rglob("*"):
        if path.is_symlink():
            raise WorkspaceError(f"fixture 暂不支持软链接: {path}")


@dataclass
class PreparedWorkspace:
    task_id: str
    source: Path
    container: Path
    path: Path
    keep: bool = False
    _cleaned: bool = False

    @property
    def marker_path(self) -> Path:
        return self.container / ".zzhclaw-eval-owner.json"

    def cleanup(self) -> None:
        if self._cleaned or self.keep:
            return
        if not self.marker_path.is_file():
            raise WorkspaceError(f"拒绝清理缺少 owner marker 的目录: {self.container}")
        try:
            marker = json.loads(self.marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkspaceError(
                f"无法验证工作区 owner marker: {self.marker_path}"
            ) from exc
        if marker.get("task_id") != self.task_id or marker.get("workspace") != str(
            self.path
        ):
            raise WorkspaceError(
                f"拒绝清理 owner marker 不匹配的目录: {self.container}"
            )
        shutil.rmtree(self.container)
        self._cleaned = True

    def __enter__(self) -> "PreparedWorkspace":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.cleanup()


class WorkspaceManager:
    """从只读 fixture 创建任务工作副本。"""

    def __init__(self, benchmark: LoadedBenchmark, run_root: str | Path):
        self.benchmark = benchmark
        self.run_root = Path(run_root).expanduser().resolve()
        self.workspaces_root = self.run_root / "workspaces"
        self.workspaces_root.mkdir(parents=True, exist_ok=True)

    def prepare(self, task: EvalTask, *, keep: bool = False) -> PreparedWorkspace:
        source = self.benchmark.fixture_path(task)
        _reject_symlinks(source)

        container = Path(
            tempfile.mkdtemp(
                prefix=f"{_safe_name(task.id)}-",
                dir=self.workspaces_root,
            )
        ).resolve()
        path = container / "repo"
        try:
            shutil.copytree(
                source,
                path,
                ignore=shutil.ignore_patterns(
                    "__pycache__", "*.pyc", "*.pyo", "*.lock", ".pytest_cache"
                ),
            )
            marker = {
                "task_id": task.id,
                "source": str(source),
                "workspace": str(path),
            }
            (container / ".zzhclaw-eval-owner.json").write_text(
                json.dumps(marker, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            shutil.rmtree(container, ignore_errors=True)
            raise

        return PreparedWorkspace(
            task_id=task.id,
            source=source,
            container=container,
            path=path,
            keep=keep,
        )
