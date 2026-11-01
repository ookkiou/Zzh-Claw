from dataclasses import replace

from fake_llm import tool_call

from zzhclaw.eval.metrics import aggregate
from zzhclaw.eval.models import TraceEvent, ValidatorResult
from zzhclaw.eval.recorder import TrajectoryRecorder
from zzhclaw.runtime import ToolResult


def test_agent_passes_command_error_metadata_to_trace(make_agent, monkeypatch):
    from zzhclaw.agent import core

    monkeypatch.setattr(
        core,
        "execute_tool",
        lambda *args: ToolResult(
            "pytest did not pass",
            error_code="command_failed",
            metadata={"command": {"exit_code": 1}},
        ),
    )
    agent = make_agent(
        [tool_call("run_bash", '{"command":"pytest"}'), "done"], system_prompt=None
    )
    trace = TrajectoryRecorder()
    assert agent.run("fix", on_event=trace) == "done"
    result = next(e for e in trace.events if e.event_type == "tool_result")
    assert result.error == "command_failed"
    assert result.metadata["command"]["exit_code"] == 1
    assert result.metadata["result_schema_version"] == 1


def test_success_text_is_not_misclassified_as_error_or_violation():
    trace = TrajectoryRecorder()
    trace.record(
        "tool_result",
        result="错误: 用户希望查找的文本，危险命令，写入被沙箱拒绝",
        metadata={"result_schema_version": 1, "error_code": None},
    )
    assert (
        trace.count_tool_error("workspace_violation", legacy_text="写入被沙箱拒绝") == 0
    )
    assert trace.count_tool_error("policy_rejected", legacy_text="危险命令") == 0
    trace.record(
        "tool_result",
        result="blocked",
        metadata={"result_schema_version": 1, "error_code": "policy_rejected"},
    )
    assert trace.count_tool_error("policy_rejected", legacy_text="危险命令") == 1


def test_legacy_validator_result_loads_with_new_optional_fields():
    legacy = ValidatorResult.from_dict({"exit_code": 0, "stdout": "ok"})
    assert not legacy.stdout_truncated and legacy.error_code is None
    updated = replace(legacy, stdout_truncated=True, error_code="command_failed")
    assert ValidatorResult.from_dict(updated.to_dict()) == updated


def test_structured_metric_error_codes_override_message_text():
    from zzhclaw.eval.models import TaskRunResult

    result = TaskRunResult(
        run_id="r",
        task_id="a",
        benchmark="b",
        model="m",
        status="passed",
        started_at="s",
        finished_at="f",
        duration_ms=1,
        tool_calls=2,
    )
    events = [
        TraceEvent(
            sequence=0, event_type="tool_call", tool_name="run_bash", arguments={}
        ),
        TraceEvent(
            sequence=1,
            event_type="tool_result",
            result="错误: just text",
            metadata={"result_schema_version": 1, "error_code": None},
        ),
        TraceEvent(
            sequence=2, event_type="tool_call", tool_name="run_bash", arguments={}
        ),
        TraceEvent(
            sequence=3,
            event_type="tool_result",
            result="tests failed",
            metadata={"result_schema_version": 1, "error_code": "command_failed"},
        ),
    ]
    summary = aggregate(
        [{"result": result, "events": events, "repeat": 1}],
        {
            "run_id": "r",
            "benchmark": "b",
            "model": "m",
            "repeat": 1,
            "schedule": [{}],
            "task_specs": [{"id": "a", "tags": []}],
        },
    )
    assert summary["tool_error_rate"] == 0.5


def test_execute_tool_unknown_has_code_without_breaking_text():
    from zzhclaw.coding.tools import execute_tool

    result = execute_tool("missing-tool", {})
    assert result == "未知工具: missing-tool" and result.error_code == "unknown_tool"


def test_successful_read_of_error_text_is_not_an_error(workspace):
    from zzhclaw.coding.tools import execute_tool

    workspace.write("log.txt", "错误: 写入被沙箱拒绝")
    result = execute_tool("read_file", {"path": "log.txt"})
    assert result == "错误: 写入被沙箱拒绝" and result.error_code is None
    missing = execute_tool("read_file", {"path": "missing.txt"})
    assert missing.error_code == "tool_error"


def test_sandbox_rejection_has_structured_code(workspace, tmp_path):
    from zzhclaw.coding.tools import execute_tool

    result = execute_tool(
        "write_file", {"path": str(tmp_path / "outside.txt"), "content": "no"}
    )
    assert result.error_code == "workspace_violation"


def test_policy_rejection_is_counted_by_runner_without_matching_message(tmp_path):
    from pathlib import Path

    from fake_llm import FakeLLM

    from zzhclaw.agent import Agent
    from zzhclaw.eval import TaskRunner, load_benchmark

    manifest = (
        Path(__file__).resolve().parents[2] / "benchmarks/python_basic/benchmark.json"
    )
    benchmark = load_benchmark(manifest)

    def factory(session_manager):
        return Agent(
            llm=FakeLLM([tool_call("run_bash", '{"command":"shutdown now"}'), "done"]),
            session_manager=session_manager,
            system_prompt=None,
        )

    result = TaskRunner(
        benchmark, tmp_path / "run", factory, run_id="r", model="fake"
    ).run(benchmark.task_by_id("python-001"))
    assert result.safety.dangerous_command_rejections == 1
