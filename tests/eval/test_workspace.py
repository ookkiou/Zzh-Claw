from pathlib import Path

import pytest

from zzhclaw.eval import WorkspaceError, WorkspaceManager, load_benchmark

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_MANIFEST = REPO_ROOT / "benchmarks" / "python_basic" / "benchmark.json"


def sample():
    benchmark = load_benchmark(SAMPLE_MANIFEST)
    return benchmark, benchmark.task_by_id("python-001")


def test_prepare_copies_fixture_without_modifying_source(tmp_path):
    benchmark, task = sample()
    source = benchmark.fixture_path(task)
    original = (source / "calculator.py").read_text(encoding="utf-8")
    manager = WorkspaceManager(benchmark, tmp_path / "run")

    with manager.prepare(task) as prepared:
        copied = prepared.path / "calculator.py"
        assert copied.read_text(encoding="utf-8") == original
        copied.write_text("changed", encoding="utf-8")
        assert (source / "calculator.py").read_text(encoding="utf-8") == original
        container = prepared.container

    assert not container.exists()


def test_prepare_creates_unique_workspaces_for_same_task(tmp_path):
    benchmark, task = sample()
    manager = WorkspaceManager(benchmark, tmp_path / "run")

    first = manager.prepare(task)
    second = manager.prepare(task)
    try:
        assert first.path != second.path
        assert first.path.is_dir() and second.path.is_dir()
    finally:
        first.cleanup()
        second.cleanup()


def test_keep_preserves_workspace(tmp_path):
    benchmark, task = sample()
    manager = WorkspaceManager(benchmark, tmp_path / "run")

    prepared = manager.prepare(task, keep=True)
    prepared.cleanup()

    assert prepared.path.is_dir()


def test_cleanup_refuses_directory_without_owner_marker(tmp_path):
    benchmark, task = sample()
    manager = WorkspaceManager(benchmark, tmp_path / "run")
    prepared = manager.prepare(task)
    prepared.marker_path.unlink()

    with pytest.raises(WorkspaceError, match="owner marker"):
        prepared.cleanup()


def test_prepare_rejects_symlink_in_fixture(tmp_path):
    root = tmp_path / "benchmark"
    fixture = root / "fixtures" / "task-1"
    fixture.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (fixture / "link.txt").symlink_to(outside)
    (root / "benchmark.json").write_text(
        '{"name":"demo","version":"0.1.0","description":"",'
        '"task_file":"tasks.jsonl","created_at":"2026-10-09"}',
        encoding="utf-8",
    )
    (root / "tasks.jsonl").write_text(
        '{"id":"task-1","title":"t","prompt":"p",'
        '"workspace":"fixtures/task-1",'
        '"validator":{"command":["python","test.py"]}}\n',
        encoding="utf-8",
    )
    benchmark = load_benchmark(root / "benchmark.json")
    manager = WorkspaceManager(benchmark, tmp_path / "run")

    with pytest.raises(WorkspaceError, match="软链接"):
        manager.prepare(benchmark.tasks[0])
