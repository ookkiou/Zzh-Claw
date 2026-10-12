import json

import pytest

from zzhclaw.eval.models import (
    BenchmarkManifest,
    EvalTask,
    SafetyMetrics,
    TaskRunResult,
    TraceEvent,
    UsageMetrics,
    ValidatorConfig,
    ValidatorResult,
)


def validator():
    return ValidatorConfig(
        command=("python", "-m", "pytest", "-q"),
        timeout_seconds=30,
        env={"PYTHONPATH": "{workspace}"},
    )


def manifest():
    return BenchmarkManifest(
        name="demo",
        version="0.1.0",
        description="demo benchmark",
        task_file="tasks.jsonl",
        created_at="2026-10-09",
        default_timeout_seconds=180,
        default_max_iterations=12,
    )


def test_manifest_identity_and_json_shape():
    item = manifest()

    assert item.identity == "demo@0.1.0"
    assert item.to_dict()["task_file"] == "tasks.jsonl"
    json.dumps(item.to_dict())


def test_task_uses_manifest_defaults_without_mutating_original():
    task = EvalTask(
        id="task-1",
        title="任务",
        prompt="修复代码",
        workspace="fixtures/task-1",
        validator=validator(),
        tags=("python",),
    )

    resolved = task.with_defaults(manifest())

    assert task.max_iterations is None
    assert resolved.max_iterations == 12
    assert resolved.task_timeout_seconds == 180


def test_task_round_trip_keeps_nested_validator_and_lists():
    task = EvalTask(
        id="task-1",
        title="任务",
        prompt="修复代码",
        workspace="fixtures/task-1",
        validator=validator(),
        max_iterations=8,
        task_timeout_seconds=90,
        tags=("python", "bugfix"),
        split="dev",
        difficulty="medium",
    )

    raw = task.to_dict()
    restored = EvalTask.from_dict(raw)

    assert raw["tags"] == ["python", "bugfix"]
    assert raw["validator"]["command"] == ["python", "-m", "pytest", "-q"]
    assert restored == task


@pytest.mark.parametrize(
    "field,value",
    [
        ("split", "unknown"),
        ("difficulty", "extreme"),
        ("max_iterations", 0),
    ],
)
def test_task_rejects_invalid_fields(field, value):
    kwargs = {
        "id": "task-1",
        "title": "任务",
        "prompt": "修复代码",
        "workspace": "fixtures/task-1",
        "validator": validator(),
    }
    kwargs[field] = value

    with pytest.raises(ValueError):
        EvalTask(**kwargs)


def test_task_rejects_duplicate_tags():
    with pytest.raises(ValueError, match="重复"):
        EvalTask(
            id="task-1",
            title="任务",
            prompt="修复代码",
            workspace="fixtures/task-1",
            validator=validator(),
            tags=("python", "python"),
        )


def test_trace_event_round_trip():
    event = TraceEvent(
        sequence=1,
        event_type="tool_call",
        timestamp="2026-10-09T10:00:00+08:00",
        tool_call_id="call-1",
        tool_name="read_file",
        arguments={"path": "app.py"},
        metadata={"iteration": 1},
    )

    assert TraceEvent.from_dict(event.to_dict()) == event


def test_trace_event_rejects_unknown_type_and_negative_duration():
    with pytest.raises(ValueError, match="event_type"):
        TraceEvent(sequence=0, event_type="unknown")
    with pytest.raises(ValueError, match="duration_ms"):
        TraceEvent(sequence=0, event_type="agent_start", duration_ms=-1)


def test_task_run_result_round_trip():
    result = TaskRunResult(
        run_id="run-1",
        task_id="task-1",
        benchmark="demo@0.1.0",
        model="fake-model",
        status="passed",
        started_at="2026-10-09T10:00:00+08:00",
        finished_at="2026-10-09T10:00:01+08:00",
        duration_ms=1000,
        agent_iterations=2,
        tool_calls=3,
        final_answer="完成",
        validator=ValidatorResult(exit_code=0, duration_ms=10, stdout="1 passed"),
        usage=UsageMetrics(input_tokens=10, output_tokens=5),
        safety=SafetyMetrics(workspace_violations=0),
        trace_file="tasks/task-1/trace.jsonl",
    )

    restored = TaskRunResult.from_dict(result.to_dict())

    assert restored == result
    json.dumps(result.to_dict(), ensure_ascii=False)


def test_task_run_result_rejects_unknown_status():
    with pytest.raises(ValueError, match="status"):
        TaskRunResult(
            run_id="run-1",
            task_id="task-1",
            benchmark="demo@0.1.0",
            model="fake-model",
            status="maybe",
            started_at="start",
            finished_at="finish",
            duration_ms=0,
        )
