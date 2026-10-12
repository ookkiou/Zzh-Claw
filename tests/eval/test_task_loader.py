import json
from pathlib import Path

import pytest

from zzhclaw.eval import BenchmarkLoadError, load_benchmark

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_MANIFEST = REPO_ROOT / "benchmarks" / "python_basic" / "benchmark.json"


def write_benchmark(tmp_path, tasks, *, task_file="tasks.jsonl"):
    root = tmp_path / "benchmark"
    root.mkdir()
    (root / "fixtures" / "task-1").mkdir(parents=True)
    (root / "fixtures" / "task-2").mkdir(parents=True)
    manifest = {
        "name": "demo",
        "version": "0.1.0",
        "description": "demo",
        "task_file": task_file,
        "created_at": "2026-10-09",
        "default_timeout_seconds": 99,
        "default_max_iterations": 7,
    }
    (root / "benchmark.json").write_text(json.dumps(manifest), encoding="utf-8")
    if task_file == "tasks.jsonl":
        lines = "\n".join(json.dumps(task, ensure_ascii=False) for task in tasks)
        (root / task_file).write_text(lines + "\n", encoding="utf-8")
    return root


def task(task_id="task-1", *, workspace="fixtures/task-1", split="test", tags=None):
    return {
        "id": task_id,
        "title": "任务",
        "prompt": "修复代码",
        "workspace": workspace,
        "validator": {"command": ["python", "validator.py"]},
        "split": split,
        "tags": tags or ["python"],
    }


def test_repository_benchmark_loads_thirty_tasks_with_defaults():
    benchmark = load_benchmark(SAMPLE_MANIFEST)

    assert benchmark.identity == "python-basic@0.1.0"
    assert [item.id for item in benchmark.tasks] == [
        f"python-{number:03d}" for number in range(1, 31)
    ]
    assert benchmark.task_by_id("python-001").max_iterations == 12
    assert benchmark.task_by_id("python-002").max_iterations == 12
    assert all(benchmark.fixture_path(item).is_dir() for item in benchmark.tasks)


def test_loader_filters_by_split_and_all_requested_tags(tmp_path):
    root = write_benchmark(
        tmp_path,
        [
            task("task-1", split="dev", tags=["python", "bugfix"]),
            task("task-2", workspace="fixtures/task-2", split="test", tags=["python"]),
        ],
    )

    dev = load_benchmark(
        root / "benchmark.json", split="dev", tags=["python", "bugfix"]
    )

    assert [item.id for item in dev.tasks] == ["task-1"]


def test_loader_rejects_duplicate_task_ids(tmp_path):
    root = write_benchmark(tmp_path, [task(), task()])

    with pytest.raises(BenchmarkLoadError, match="ID 重复"):
        load_benchmark(root / "benchmark.json")


def test_loader_reports_jsonl_line_number(tmp_path):
    root = write_benchmark(tmp_path, [task()])
    valid = json.dumps(task(), ensure_ascii=False)
    (root / "tasks.jsonl").write_text(valid + "\n{broken\n", encoding="utf-8")

    with pytest.raises(BenchmarkLoadError, match=r"tasks\.jsonl:2"):
        load_benchmark(root / "benchmark.json")


def test_loader_rejects_task_file_path_escape(tmp_path):
    root = write_benchmark(tmp_path, [], task_file="../outside.jsonl")
    (tmp_path / "outside.jsonl").write_text("", encoding="utf-8")

    with pytest.raises(BenchmarkLoadError, match="目录之外"):
        load_benchmark(root / "benchmark.json")


def test_loader_rejects_workspace_path_escape(tmp_path):
    root = write_benchmark(tmp_path, [task(workspace="../../outside")])
    (tmp_path / "outside").mkdir()

    with pytest.raises(BenchmarkLoadError, match="目录之外"):
        load_benchmark(root / "benchmark.json")


def test_loader_rejects_missing_workspace(tmp_path):
    root = write_benchmark(tmp_path, [task(workspace="fixtures/missing")])

    with pytest.raises(BenchmarkLoadError, match="不存在或不是目录"):
        load_benchmark(root / "benchmark.json")


def test_task_by_id_raises_key_error_for_unknown_task():
    benchmark = load_benchmark(SAMPLE_MANIFEST)

    with pytest.raises(KeyError):
        benchmark.task_by_id("unknown")
