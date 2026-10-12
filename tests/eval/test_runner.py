import json
from dataclasses import replace
from pathlib import Path

from fake_llm import FakeLLM, tool_call

from zzhclaw.agent import Agent
from zzhclaw.coding.tools import get_cwd, get_sandbox
from zzhclaw.eval import TaskRunner, ValidatorConfig, load_benchmark

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_MANIFEST = REPO_ROOT / "benchmarks" / "python_basic" / "benchmark.json"


def factory(script):
    def build(session_manager):
        return Agent(
            llm=FakeLLM(script),
            session_manager=session_manager,
            system_prompt=None,
            permission_mode="auto",
        )

    return build


def test_runner_completes_edit_validate_trace_and_result(tmp_path):
    benchmark = load_benchmark(SAMPLE_MANIFEST)
    task = benchmark.task_by_id("python-002")
    script = [
        tool_call(
            "edit_file",
            json.dumps(
                {
                    "path": "text_utils.py",
                    "old_text": "    raise NotImplementedError",
                    "new_text": '    return " ".join(text.split())',
                }
            ),
            call_id="edit-1",
        ),
        "实现完成，测试应可通过。",
    ]
    run_root = tmp_path / "run"
    previous_cwd = get_cwd()
    previous_sandbox = get_sandbox()
    runner = TaskRunner(
        benchmark,
        run_root,
        factory(script),
        run_id="run-1",
        model="fake-model",
    )

    result = runner.run(task)

    assert result.status == "passed"
    assert result.validator.exit_code == 0
    assert result.tool_calls == 1
    assert result.agent_iterations == 2
    assert result.final_answer == "实现完成，测试应可通过。"
    assert get_cwd() == previous_cwd
    assert get_sandbox() == previous_sandbox

    task_dir = run_root / "tasks" / task.id
    saved = json.loads((task_dir / "result.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (task_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert saved["status"] == "passed"
    assert [event["event_type"] for event in events] == [
        "agent_start",
        "tool_call",
        "tool_result",
        "agent_final",
        "validator_start",
        "validator_result",
    ]
    assert list((run_root / "workspaces").iterdir()) == []
    assert not list(task_dir.glob(".result.json.*.tmp"))


def test_runner_records_failed_validation(tmp_path):
    benchmark = load_benchmark(SAMPLE_MANIFEST)
    task = benchmark.task_by_id("python-001")
    runner = TaskRunner(
        benchmark,
        tmp_path / "run",
        factory(["没有修改代码"]),
        run_id="run-1",
        model="fake-model",
    )

    result = runner.run(task)

    assert result.status == "failed"
    assert result.validator.exit_code != 0
    assert result.error is None


def test_runner_converts_llm_exception_to_agent_error(tmp_path):
    class BrokenLLM:
        def chat_stream(self, messages, tools=None):
            raise RuntimeError("offline")

        def summarize(self, existing_summary, messages):
            return ""

    benchmark = load_benchmark(SAMPLE_MANIFEST)
    task = benchmark.task_by_id("python-001")

    def build(session_manager):
        return Agent(
            llm=BrokenLLM(), session_manager=session_manager, system_prompt=None
        )

    run_root = tmp_path / "run"
    result = TaskRunner(
        benchmark,
        run_root,
        build,
        run_id="run-1",
        model="broken-model",
    ).run(task)

    assert result.status == "agent_error"
    assert "offline" in result.error
    saved = json.loads(
        (run_root / "tasks" / task.id / "result.json").read_text(encoding="utf-8")
    )
    assert saved["status"] == "agent_error"


def test_runner_converts_missing_validator_command_to_validator_error(tmp_path):
    benchmark = load_benchmark(SAMPLE_MANIFEST)
    original = benchmark.task_by_id("python-001")
    task = replace(
        original,
        validator=ValidatorConfig(command=("definitely-not-a-real-command-zzhclaw",)),
    )
    result = TaskRunner(
        benchmark,
        tmp_path / "run",
        factory(["完成"]),
        run_id="run-1",
        model="fake-model",
    ).run(task)

    assert result.status == "validator_error"
    assert "无法启动" in result.error


def test_runner_can_preserve_failed_workspace(tmp_path):
    benchmark = load_benchmark(SAMPLE_MANIFEST)
    task = benchmark.task_by_id("python-001")
    run_root = tmp_path / "run"
    result = TaskRunner(
        benchmark,
        run_root,
        factory(["未修改"]),
        run_id="run-1",
        model="fake-model",
        keep_failed_workspace=True,
    ).run(task)

    assert result.status == "failed"
    kept = list((run_root / "workspaces").iterdir())
    assert len(kept) == 1
    assert (kept[0] / "repo" / "calculator.py").is_file()
