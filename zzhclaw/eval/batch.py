"""顺序批量评测、运行身份与断点续跑。"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from .models import TaskRunResult, TraceEvent, utc_now_iso
from .runner import TaskRunner
from .storage import write_json_atomic
from .task_loader import LoadedBenchmark


def benchmark_digest(benchmark: LoadedBenchmark) -> str:
    """为任务与评测资源建立指纹；不扫描项目配置或运行目录。"""
    digest = hashlib.sha256()
    files = {benchmark.manifest_path, benchmark.task_file}
    roots = [benchmark.fixture_path(task) for task in benchmark.tasks]
    if (benchmark.root / "validators").is_dir():
        roots.append(benchmark.root / "validators")
    if (benchmark.root / "references").is_dir():
        roots.append(benchmark.root / "references")
    for root in roots:
        for path in root.rglob("*"):
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".lock"}:
                continue
            if path.is_symlink():
                raise ValueError(f"benchmark 资源暂不支持软链接: {path}")
            if path.is_file():
                files.add(path)
    for path in sorted(files):
        digest.update(str(path.relative_to(benchmark.root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def source_revision() -> dict:
    """只记录 Git 身份；不读取用户凭据或远端 URL。"""
    root = Path(__file__).resolve().parents[2]
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout
        return {"git_commit": commit, "dirty_worktree": bool(dirty)}
    except (OSError, subprocess.SubprocessError):
        return {"git_commit": None, "dirty_worktree": None}


def implementation_digest() -> str:
    digest = hashlib.sha256()
    root = Path(__file__).resolve().parents[1]
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def read_attempt(directory: Path, *, manifest: dict, task_id: str) -> TaskRunResult:
    result = TaskRunResult.from_dict(
        json.loads((directory / "result.json").read_text())
    )
    if (result.task_id, result.run_id, result.benchmark, result.model) != (
        task_id,
        manifest["run_id"],
        manifest["benchmark"],
        manifest["model"],
    ):
        raise ValueError(f"结果身份不匹配: {directory}")
    events = [
        TraceEvent.from_dict(json.loads(line))
        for line in (directory / "trace.jsonl").read_text().splitlines()
        if line.strip()
    ]
    if not events or [event.sequence for event in events] != list(range(len(events))):
        raise ValueError(f"轨迹为空或序号无效: {directory}")
    terminal = events[-1]
    if result.status in {"passed", "failed", "timeout", "validator_error"}:
        complete = (
            terminal.event_type == "validator_result"
            and terminal.metadata.get("status") == result.status
        )
        if result.status == "timeout" and terminal.event_type == "agent_error":
            complete = terminal.metadata.get("status") == "timeout"
    else:
        complete = terminal.event_type == "agent_error"
    if (
        not complete
        or sum(event.event_type == "tool_call" for event in events) != result.tool_calls
    ):
        raise ValueError(f"结果与轨迹不一致或轨迹未完成: {directory}")
    return result


class BatchRunner:
    """每次 attempt 使用独立目录；只恢复配置与资源完全匹配的运行。"""

    def __init__(
        self,
        benchmark,
        run_root,
        agent_factory,
        *,
        model,
        repeat=1,
        task_ids=None,
        configuration=None,
        keep_workspaces=False,
        keep_failed_workspace=False,
    ):
        if isinstance(repeat, bool) or not isinstance(repeat, int) or repeat < 1:
            raise ValueError("repeat 必须是正整数")
        self.benchmark = benchmark
        self.root = Path(run_root).expanduser().resolve()
        self.agent_factory = agent_factory
        self.model = model
        self.repeat = repeat
        selected = set(task_ids or [])
        known = {task.id for task in benchmark.tasks}
        if selected - known:
            raise ValueError(f"未知或被筛选掉的任务: {sorted(selected - known)}")
        self.tasks = tuple(
            task for task in benchmark.tasks if not selected or task.id in selected
        )
        if not self.tasks:
            raise ValueError("筛选后没有任务")
        if self.root.is_relative_to(benchmark.root):
            raise ValueError("输出目录不能位于 benchmark 内，避免污染任务资源")
        self.configuration = configuration or {}
        self.keep_workspaces = keep_workspaces
        self.keep_failed_workspace = keep_failed_workspace

    def run(self, *, resume=False, fail_fast=False, on_progress=None) -> dict:
        identity = {
            "schema_version": 1,
            "benchmark": self.benchmark.identity,
            "benchmark_digest": benchmark_digest(self.benchmark),
            "implementation_digest": implementation_digest(),
            "model": self.model,
            "configuration": self.configuration,
            "task_specs": [task.to_dict() for task in self.tasks],
            "repeat": self.repeat,
            "schedule": [
                {
                    "task_id": task.id,
                    "repeat": index,
                    "directory": f"attempts/repeat-{index:03d}/tasks/{task.id}",
                }
                for index in range(1, self.repeat + 1)
                for task in self.tasks
            ],
        }
        manifest_path = self.root / "manifest.json"
        if resume:
            if not manifest_path.is_file():
                raise ValueError("--resume 需要已有 manifest.json")
            manifest = json.loads(manifest_path.read_text())
            if any(manifest.get(key) != value for key, value in identity.items()):
                raise ValueError(
                    "续跑配置、任务或源码与原运行不一致，请使用新的输出目录"
                )
        else:
            if self.root.exists() and any(self.root.iterdir()):
                raise ValueError("输出目录非空；请使用 --resume 或新目录")
            self.root.mkdir(parents=True, exist_ok=True)
            manifest = {
                **identity,
                "run_id": self.root.name,
                "started_at": utc_now_iso(),
                **source_revision(),
            }
            write_json_atomic(manifest_path, manifest)

        executed = resumed = 0
        interrupted = False
        by_id = {task.id: task for task in self.tasks}
        try:
            for attempt in identity["schedule"]:
                directory = self.root / attempt["directory"]
                saved = None
                if resume:
                    try:
                        saved = read_attempt(
                            directory, manifest=manifest, task_id=attempt["task_id"]
                        )
                    except (OSError, ValueError, TypeError, KeyError):
                        pass  # 缺失或损坏的产物必须重跑
                if saved is not None and saved.status != "cancelled":
                    resumed += 1
                    if on_progress:
                        on_progress(attempt, saved, True)
                    continue
                task = by_id[attempt["task_id"]]
                # Runner 每次建立新 Session，不加载旧会话。
                runner = TaskRunner(
                    self.benchmark,
                    directory.parents[1],
                    self.agent_factory,
                    run_id=manifest["run_id"],
                    model=self.model,
                    keep_workspaces=self.keep_workspaces,
                    keep_failed_workspace=self.keep_failed_workspace,
                )
                result = runner.run(task)
                executed += 1
                if on_progress:
                    on_progress(attempt, result, False)
                if result.status == "cancelled":
                    interrupted = True
                    break
                if fail_fast and result.status != "passed":
                    break
        except KeyboardInterrupt:
            interrupted = True

        from .report import generate_report

        summary = generate_report(self.root)
        return {
            "executed": executed,
            "resumed": resumed,
            "interrupted": interrupted,
            "summary": summary,
        }
