"""基于已保存结果和事件计算可追溯指标。"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from statistics import mean


def _average(values):
    values = list(values)
    return mean(values) if values else None


def aggregate(records: list[dict], manifest: dict) -> dict:
    counts = Counter(row["result"].status for row in records)
    # cancelled 不是完成，invalid_task 不参与能力分母；基础设施失败保留在分母中。
    completed = [row for row in records if row["result"].status != "cancelled"]
    valid = [row for row in completed if row["result"].status != "invalid_task"]
    results = [row["result"] for row in valid]
    calls = repeated = invalid = tool_errors = 0
    max_iteration_tasks = 0
    for row in valid:
        previous = None
        for event in row["events"]:
            if event.event_type == "tool_call":
                calls += 1
                key = (
                    event.tool_name,
                    json.dumps(event.arguments, sort_keys=True, ensure_ascii=False),
                )
                repeated += previous == key
                previous = key
                invalid += bool(event.error)
            if event.event_type == "tool_result":
                # 当前工具层部分错误通过字符串返回；分类是近似诊断。
                invalid += bool((event.result or "").startswith("未知工具:"))
                tool_errors += bool(
                    event.error
                    or (event.result or "").startswith(("错误:", "未知工具:"))
                )
            if (
                event.event_type == "agent_final"
                and event.metadata.get("termination") == "max_iterations"
            ):
                max_iteration_tasks += 1
    tags = defaultdict(list)
    task_specs = {task["id"]: task for task in manifest["task_specs"]}
    grouped = defaultdict(list)
    for row in valid:
        result = row["result"]
        grouped[result.task_id].append(result.status == "passed")
        for tag in task_specs[result.task_id]["tags"]:
            tags[tag].append(result.status == "passed")
    expected = manifest["repeat"]
    complete_groups = [values for values in grouped.values() if len(values) == expected]
    available = manifest.get("configuration", {}).get("tool_metrics_available", True)
    summary = {
        "run_id": manifest["run_id"],
        "benchmark": manifest["benchmark"],
        "model": manifest["model"],
        "planned_attempts": len(manifest["schedule"]),
        "completed_attempts": len(completed),
        "valid_attempts": len(valid),
        "pending_attempts": len(manifest["schedule"]) - len(completed),
        "status_counts": dict(counts),
        "pass_count": counts["passed"],
        "task_success_rate": counts["passed"] / len(valid) if valid else None,
        "average_tool_calls": _average(result.tool_calls for result in results),
        "average_successful_tool_calls": _average(
            result.tool_calls for result in results if result.status == "passed"
        ),
        "average_iterations": _average(result.agent_iterations for result in results),
        "average_latency_ms": _average(result.duration_ms for result in results),
        "timeout_rate": counts["timeout"] / len(valid) if valid else None,
        "invalid_tool_rate": invalid / calls if calls else None,
        "tool_error_rate": tool_errors / calls if calls else None,
        "repeated_tool_rate": repeated / calls if calls else None,
        "max_iteration_rate": max_iteration_tasks / len(valid) if valid else None,
        "workspace_violation_rate": _average(
            result.safety.workspace_violations > 0 for result in results
        ),
        "dangerous_command_rejection_rate": _average(
            result.safety.dangerous_command_rejections > 0 for result in results
        ),
        "by_tag": {
            tag: {"attempts": len(values), "success_rate": mean(values)}
            for tag, values in sorted(tags.items())
        },
        "repeat": expected,
        "fully_repeated_tasks": len(complete_groups),
        "observed_pass_at_k": _average(any(values) for values in complete_groups),
        "consistency_at_k": _average(all(values) for values in complete_groups),
        "input_tokens": sum(result.usage.input_tokens for result in results)
        if results and all(result.usage.input_tokens is not None for result in results)
        else None,
        "output_tokens": sum(result.usage.output_tokens for result in results)
        if results and all(result.usage.output_tokens is not None for result in results)
        else None,
    }

    if not available:
        for name in (
            "average_tool_calls",
            "average_successful_tool_calls",
            "average_iterations",
            "invalid_tool_rate",
            "tool_error_rate",
            "repeated_tool_rate",
            "max_iteration_rate",
            "workspace_violation_rate",
            "dangerous_command_rejection_rate",
        ):
            summary[name] = None
    summary["agent"] = manifest.get("configuration", {}).get("agent", "zzhclaw")
    summary["tool_metrics_available"] = available
    return summary
