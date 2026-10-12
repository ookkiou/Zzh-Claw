"""Benchmark manifest 与 JSONL 任务加载。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

from .models import BenchmarkManifest, EvalTask


class BenchmarkLoadError(ValueError):
    """Benchmark 文件、结构或路径不合法。"""


def _inside(base: Path, candidate: Path, label: str) -> Path:
    base = base.resolve()
    candidate = candidate.resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise BenchmarkLoadError(
            f"{label} 不能指向 benchmark 目录之外: {candidate}"
        ) from exc
    return candidate


def _load_json(path: Path, label: str) -> Dict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BenchmarkLoadError(f"无法读取{label}: {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BenchmarkLoadError(
            f"{label}不是合法 JSON: {path}:{exc.lineno}:{exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(data, dict):
        raise BenchmarkLoadError(f"{label}顶层必须是 JSON object: {path}")
    return data


def _load_jsonl(path: Path) -> Iterable[Tuple[int, Dict]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BenchmarkLoadError(f"无法读取任务文件: {path}: {exc}") from exc

    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BenchmarkLoadError(
                f"任务文件 JSON 无效: {path}:{line_no}:{exc.colno}: {exc.msg}"
            ) from exc
        if not isinstance(data, dict):
            raise BenchmarkLoadError(f"任务必须是 JSON object: {path}:{line_no}")
        yield line_no, data


@dataclass(frozen=True)
class LoadedBenchmark:
    manifest_path: Path
    root: Path
    manifest: BenchmarkManifest
    task_file: Path
    tasks: Tuple[EvalTask, ...]

    @property
    def identity(self) -> str:
        return self.manifest.identity

    def task_by_id(self, task_id: str) -> EvalTask:
        for task in self.tasks:
            if task.id == task_id:
                return task
        raise KeyError(task_id)

    def fixture_path(self, task: EvalTask) -> Path:
        candidate = _inside(
            self.root, self.root / task.workspace, f"任务 {task.id} 的 workspace"
        )
        if not candidate.is_dir():
            raise BenchmarkLoadError(
                f"任务 {task.id} 的 workspace 不存在或不是目录: {candidate}"
            )
        return candidate


def load_benchmark(
    manifest_path: str | Path,
    *,
    split: Optional[str] = None,
    tags: Optional[Iterable[str]] = None,
) -> LoadedBenchmark:
    """加载并校验 benchmark。

    ``tags`` 使用 AND 语义：任务必须包含全部指定标签。
    """
    path = Path(manifest_path).expanduser().resolve()
    if not path.is_file():
        raise BenchmarkLoadError(f"benchmark manifest 不存在或不是文件: {path}")
    root = path.parent.resolve()

    try:
        manifest = BenchmarkManifest.from_dict(_load_json(path, "benchmark manifest"))
    except ValueError as exc:
        raise BenchmarkLoadError(f"benchmark manifest 字段无效: {exc}") from exc

    task_file = _inside(root, root / manifest.task_file, "manifest.task_file")
    if not task_file.is_file():
        raise BenchmarkLoadError(f"任务文件不存在或不是文件: {task_file}")

    if split is not None and split not in {"train", "dev", "test"}:
        raise BenchmarkLoadError("split 必须是 train、dev 或 test")
    requested_tags = tuple(tags or ())
    if any(not isinstance(tag, str) or not tag for tag in requested_tags):
        raise BenchmarkLoadError("tags 必须是非空字符串")
    required_tags = set(requested_tags)

    tasks = []
    seen_ids = set()
    for line_no, raw in _load_jsonl(task_file):
        try:
            task = EvalTask.from_dict(raw).with_defaults(manifest)
        except ValueError as exc:
            raise BenchmarkLoadError(
                f"任务字段无效: {task_file}:{line_no}: {exc}"
            ) from exc
        if task.id in seen_ids:
            raise BenchmarkLoadError(f"任务 ID 重复: {task.id} ({task_file}:{line_no})")
        seen_ids.add(task.id)

        fixture = _inside(root, root / task.workspace, f"任务 {task.id} 的 workspace")
        if not fixture.is_dir():
            raise BenchmarkLoadError(
                f"任务 {task.id} 的 workspace 不存在或不是目录: {fixture}"
            )

        if split is not None and task.split != split:
            continue
        if required_tags and not required_tags.issubset(task.tags):
            continue
        tasks.append(task)

    return LoadedBenchmark(
        manifest_path=path,
        root=root,
        manifest=manifest,
        task_file=task_file,
        tasks=tuple(tasks),
    )
