import json
import sys
from dataclasses import replace

import pytest
from fake_llm import FakeLLM, tool_call

from zzhclaw.agent import Agent
from zzhclaw.eval import BatchRunner, load_benchmark
from zzhclaw.eval.cli import main
from zzhclaw.eval.compare import compare_runs, comparison_markdown
from zzhclaw.eval.metrics import aggregate
from zzhclaw.eval.models import TraceEvent
from zzhclaw.eval.report import generate_report, load_run


@pytest.fixture
def benchmark(tmp_path):
    root = tmp_path / "benchmark"
    root.mkdir()
    tasks = []
    for index in range(5):
        fixture = root / "fixtures" / f"task-{index}"
        fixture.mkdir(parents=True)
        (fixture / "answer.txt").write_text("broken")
        tasks.append(
            {
                "id": f"task-{index}",
                "title": "修复文件",
                "prompt": "将 answer.txt 改成 fixed",
                "workspace": f"fixtures/task-{index}",
                "tags": ["text", "even" if index % 2 == 0 else "odd"],
                "split": "test" if index % 2 == 0 else "dev",
                "difficulty": "easy",
                "validator": {
                    "command": [
                        sys.executable,
                        "-c",
                        "import pathlib,sys;"
                        "sys.exit(pathlib.Path(sys.argv[1], 'answer.txt')"
                        ".read_text() != 'fixed')",
                        "{workspace}",
                    ]
                },
            }
        )
    (root / "tasks.jsonl").write_text("\n".join(json.dumps(task) for task in tasks))
    manifest = root / "benchmark.json"
    manifest.write_text(
        json.dumps(
            {
                "name": "five-tasks",
                "version": "0.1.0",
                "task_file": "tasks.jsonl",
                "created_at": "2026-10-09",
            }
        )
    )
    return load_benchmark(manifest)


def agent_factory(fail_indices=(), interrupt_indices=()):
    calls = []

    def build(session_manager):
        index = len(calls)
        calls.append(session_manager.storage_dir)
        if index in interrupt_indices:
            raise KeyboardInterrupt
        script = (
            ["不修改"]
            if index in fail_indices
            else [
                tool_call(
                    "write_file", json.dumps({"path": "answer.txt", "content": "fixed"})
                ),
                "完成",
            ]
        )
        return Agent(
            llm=FakeLLM(script), session_manager=session_manager, system_prompt=None
        )

    return build, calls


def run_batch(benchmark, root, *, fail_indices=(), **kwargs):
    factory, calls = agent_factory(fail_indices)
    outcome = BatchRunner(benchmark, root, factory, model="fake", **kwargs).run()
    return outcome, calls


def test_five_tasks_continue_after_failure_and_report_rebuild(benchmark, tmp_path):
    root = tmp_path / "run"
    outcome, calls = run_batch(benchmark, root, fail_indices={1})
    assert len(calls) == outcome["executed"] == 5
    assert outcome["summary"]["task_success_rate"] == 0.8
    assert outcome["summary"]["status_counts"] == {"passed": 4, "failed": 1}
    before = (root / "report.md").read_bytes()
    assert generate_report(root) == outcome["summary"]
    assert (root / "report.md").read_bytes() == before
    assert "input_tokens | N/A" in before.decode()
    assert all(
        (benchmark.fixture_path(task) / "answer.txt").read_text() == "broken"
        for task in benchmark.tasks
    )


def test_repeats_are_independent_and_resume_skips_complete_attempts(
    benchmark, tmp_path
):
    root = tmp_path / "run"
    outcome, calls = run_batch(benchmark, root, repeat=2, keep_workspaces=True)
    assert len(calls) == len(set(map(str, calls))) == 10
    assert outcome["summary"]["fully_repeated_tasks"] == 5
    assert outcome["summary"]["consistency_at_k"] == 1
    assert len(list(root.glob("attempts/*/workspaces/*/repo"))) == 10
    factory, calls = agent_factory()
    resumed = BatchRunner(benchmark, root, factory, model="fake", repeat=2).run(
        resume=True
    )
    assert resumed["executed"] == 0 and resumed["resumed"] == 10
    assert not calls


@pytest.mark.parametrize("damage", ["result", "trace", "missing", "truncated"])
def test_resume_reruns_only_damaged_attempt(benchmark, tmp_path, damage):
    root = tmp_path / "run"
    run_batch(benchmark, root)
    directory = root / "attempts/repeat-001/tasks/task-2"
    if damage == "missing":
        (directory / "result.json").unlink()
    elif damage == "truncated":
        path = directory / "trace.jsonl"
        path.write_text("\n".join(path.read_text().splitlines()[:-1]) + "\n")
    else:
        (
            directory / ("result.json" if damage == "result" else "trace.jsonl")
        ).write_text("broken")
    factory, calls = agent_factory()
    result = BatchRunner(benchmark, root, factory, model="fake").run(resume=True)
    assert result["resumed"] == 4 and result["executed"] == len(calls) == 1


@pytest.mark.parametrize("change", ["model", "repeat", "config", "fixture", "source"])
def test_resume_rejects_changed_experiment(benchmark, tmp_path, monkeypatch, change):
    root = tmp_path / "run"
    run_batch(benchmark, root)
    kwargs = {"model": "fake"}
    if change == "config":
        kwargs["configuration"] = {"prompt": "changed"}
    elif change in {"model", "repeat"}:
        kwargs[change] = "other" if change == "model" else 2
    elif change == "fixture":
        (benchmark.fixture_path(benchmark.tasks[0]) / "answer.txt").write_text(
            "changed"
        )
    else:
        monkeypatch.setattr(
            "zzhclaw.eval.batch.implementation_digest", lambda: "changed"
        )
    factory, calls = agent_factory()
    with pytest.raises(ValueError, match="不一致"):
        BatchRunner(benchmark, root, factory, **kwargs).run(resume=True)
    assert not calls


def test_interrupt_saves_partial_report_and_resume_reruns_cancelled(
    benchmark, tmp_path
):
    factory, calls = agent_factory(interrupt_indices={1})
    root = tmp_path / "run"
    result = BatchRunner(benchmark, root, factory, model="fake").run()
    assert result["interrupted"]
    assert result["summary"]["completed_attempts"] == 1
    assert result["summary"]["pending_attempts"] == 4
    factory, calls = agent_factory()
    result = BatchRunner(benchmark, root, factory, model="fake").run(resume=True)
    assert result["resumed"] == 1 and result["executed"] == len(calls) == 4
    assert result["summary"]["task_success_rate"] == 1


def test_fail_fast_reports_pending_and_does_not_fabricate_repeat_metrics(
    benchmark, tmp_path
):
    factory, _ = agent_factory(fail_indices={0})
    result = BatchRunner(
        benchmark, tmp_path / "run", factory, model="fake", repeat=2
    ).run(fail_fast=True)
    assert result["executed"] == 1
    assert result["summary"]["pending_attempts"] == 9
    assert result["summary"]["observed_pass_at_k"] is None


def test_pairwise_comparison_excludes_unpaired_attempts(benchmark, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    run_batch(benchmark, left, fail_indices={0})
    factory, _ = agent_factory(fail_indices={1})
    BatchRunner(benchmark, right, factory, model="other").run(fail_fast=True)
    result = compare_runs(left, right)
    assert result["paired_attempts"] == 2 and result["left_only"] == 3
    assert result["left_wins"] == [{"task_id": "task-1", "repeat": 1}]
    assert result["right_wins"] == [{"task_id": "task-0", "repeat": 1}]
    assert result["success_rate_delta_right_minus_left"] == 0
    assert "task-0" in comparison_markdown([left, right])
    manifest = json.loads((right / "manifest.json").read_text())
    manifest["benchmark_digest"] = "different"
    (right / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="不能比较"):
        compare_runs(left, right)


def test_metrics_denominators_repetition_and_unknown_usage(benchmark, tmp_path):
    root = tmp_path / "run"
    run_batch(benchmark, root)
    manifest, rows = load_run(root)
    rows[0]["result"] = replace(rows[0]["result"], status="invalid_task")
    rows[1]["result"] = replace(rows[1]["result"], status="cancelled")
    rows[2]["result"] = replace(rows[2]["result"], status="timeout")
    rows[2]["events"] = [
        TraceEvent(
            sequence=0, event_type="tool_call", tool_name="missing", arguments={}
        ),
        TraceEvent(sequence=1, event_type="tool_result", result="未知工具: missing"),
        TraceEvent(
            sequence=2, event_type="tool_call", tool_name="missing", arguments={}
        ),
        TraceEvent(sequence=3, event_type="tool_result", result="未知工具: missing"),
    ]
    summary = aggregate(rows, manifest)
    assert summary["valid_attempts"] == 3 and summary["completed_attempts"] == 4
    assert summary["task_success_rate"] == 2 / 3
    assert summary["timeout_rate"] == 1 / 3
    assert summary["invalid_tool_rate"] == 2 / 4
    assert summary["repeated_tool_rate"] == 1 / 4
    assert summary["input_tokens"] is None


def test_cli_validate_filters_and_errors_without_model(benchmark, capsys):
    path = str(benchmark.manifest_path)
    assert main(["validate", path, "--split", "test", "--tag", "even"]) == 0
    assert "3 个任务" in capsys.readouterr().out
    assert main(["validate", path, "--task", "unknown"]) == 2
    assert main(["validate", path, "--tag", "missing"]) == 2
    assert main(["compare", "only-one-run"]) == 2


def test_cli_run_report_compare_and_main_dispatch(benchmark, tmp_path, monkeypatch):
    import zzhclaw.__main__ as entry
    import zzhclaw.ai

    monkeypatch.setattr(zzhclaw.ai, "LLMClient", lambda **kwargs: FakeLLM(["未修改"]))
    root = tmp_path / "run"
    args = [
        "run",
        str(benchmark.manifest_path),
        "--output",
        str(root),
        "--task",
        "task-0",
        "--max-iterations",
        "1",
    ]
    assert main(args) == 1
    assert main(args + ["--resume"]) == 1
    monkeypatch.setattr(sys, "argv", ["zzhclaw", "eval", "report", str(root)])
    assert entry.main() == 0
    destination = tmp_path / "compare.md"
    assert main(["compare", str(root), str(root), "--output", str(destination)]) == 0
    assert destination.is_file()
    assert main(["run", str(benchmark.manifest_path), "--resume"]) == 2


def test_one_cli_command_runs_five_tasks_after_one_failure(
    benchmark, tmp_path, monkeypatch
):
    import zzhclaw.ai

    calls = []

    def client(**kwargs):
        index = len(calls)
        calls.append(kwargs)
        return FakeLLM(
            ["跳过"]
            if index == 1
            else [
                tool_call(
                    "write_file", json.dumps({"path": "answer.txt", "content": "fixed"})
                ),
                "完成",
            ]
        )

    monkeypatch.setattr(zzhclaw.ai, "LLMClient", client)
    root = tmp_path / "run"
    assert main(["run", str(benchmark.manifest_path), "--output", str(root)]) == 1
    assert len(calls) == 5
    saved = json.loads((root / "summary.json").read_text())
    assert saved["status_counts"] == {"passed": 4, "failed": 1}


def test_paths_and_nonempty_output_are_rejected(benchmark, tmp_path):
    factory, _ = agent_factory()
    with pytest.raises(ValueError, match="benchmark 内"):
        BatchRunner(benchmark, benchmark.root / "output", factory, model="fake")
    root = tmp_path / "run"
    run_batch(benchmark, root)
    with pytest.raises(ValueError, match="非空"):
        BatchRunner(benchmark, root, factory, model="fake").run()
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["schedule"][0]["directory"] = "../outside"
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="越界"):
        load_run(root)
