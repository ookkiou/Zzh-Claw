"""按 task ID 和重复序号配对比较已有运行。"""

from itertools import combinations

from .metrics import aggregate
from .report import cell, load_run, percentage


def compare_runs(left, right):
    a, rows_a = load_run(left)
    b, rows_b = load_run(right)
    if any(a[key] != b[key] for key in ("benchmark", "benchmark_digest")):
        raise ValueError("不能比较不同 benchmark 版本或资源内容的运行")
    index_a = {
        (row["result"].task_id, row["repeat"]): row
        for row in rows_a
        if row["result"].status not in {"cancelled", "invalid_task"}
    }
    index_b = {
        (row["result"].task_id, row["repeat"]): row
        for row in rows_b
        if row["result"].status not in {"cancelled", "invalid_task"}
    }
    common = sorted(index_a.keys() & index_b.keys())
    wins_a, wins_b, ties = [], [], []
    for key in common:
        passed_a = index_a[key]["result"].status == "passed"
        passed_b = index_b[key]["result"].status == "passed"
        target = ties if passed_a == passed_b else wins_a if passed_a else wins_b
        target.append({"task_id": key[0], "repeat": key[1]})
    paired_a = aggregate([index_a[key] for key in common], a)
    paired_b = aggregate([index_b[key] for key in common], b)
    rate_a, rate_b = paired_a["task_success_rate"], paired_b["task_success_rate"]
    return {
        "left_configuration": a.get("configuration", {}),
        "right_configuration": b.get("configuration", {}),
        "left_model": a["model"],
        "right_model": b["model"],
        "left": a["run_id"],
        "right": b["run_id"],
        "paired_attempts": len(common),
        "left_only": len(index_a.keys() - index_b.keys()),
        "right_only": len(index_b.keys() - index_a.keys()),
        "left_wins": wins_a,
        "right_wins": wins_b,
        "ties": len(ties),
        "success_rate_delta_right_minus_left": None
        if rate_a is None
        else rate_b - rate_a,
        "left_metrics": paired_a,
        "right_metrics": paired_b,
    }


def comparison_markdown(roots):
    if len(roots) < 2:
        raise ValueError("compare 至少需要两个运行目录")
    lines = [
        "# Eval 运行对比",
        "",
        "按 task ID × repeat 配对，仅比较两侧均已完成且有效的 attempt。"
        "差值为右侧减左侧。",
        "未配对结果不参与差值；随机模型的同序号重复不代表相同随机种子。",
        "",
    ]
    for left, right in combinations(roots, 2):
        data = compare_runs(left, right)
        a, b = data["left_metrics"], data["right_metrics"]
        ca, cb = data["left_configuration"], data["right_configuration"]
        lines += [
            f"## {cell(data['left'])} → {cell(data['right'])}",
            "",
            f"Agent：{cell(a['agent'])} / {cell(b['agent'])}；"
            f"模型：{cell(data['left_model'])} / {cell(data['right_model'])}。",
            f"执行：{cell(ca.get('execution', 'in_process'))} / "
            f"{cell(cb.get('execution', 'in_process'))}；Agent 时间预算："
            f"{ca.get('task_timeout_override') or '未统一覆盖'} / "
            f"{cb.get('task_timeout_override') or '未统一覆盖'} 秒。",
            "跨系统的上下文、内部重试和工具粒度可能不同；结果代表指定配置的整个系统。"
            "外部 CLI 无内部观测的指标为 N/A，不代表零调用或零违规。",
            f"配对 {data['paired_attempts']} 次；仅左侧 {data['left_only']} 次；"
            f"仅右侧 {data['right_only']} 次。",
            f"左胜 / 右胜 / 平：{len(data['left_wins'])} / "
            f"{len(data['right_wins'])} / {data['ties']}。",
            f"成功率差值：{percentage(data['success_rate_delta_right_minus_left'])}。",
            "",
            "| 配对指标 | 左侧 | 右侧 |",
            "|---|---:|---:|",
        ]
        rates = (
            "task_success_rate",
            "timeout_rate",
            "workspace_violation_rate",
            "dangerous_command_rejection_rate",
            "tool_error_rate",
            "repeated_tool_rate",
        )
        for name in rates:
            lines.append(f"| {name} | {percentage(a[name])} | {percentage(b[name])} |")
        for name in ("average_tool_calls", "average_iterations", "average_latency_ms"):
            values = [
                "N/A" if data[name] is None else f"{data[name]:.2f}" for data in (a, b)
            ]
            lines.append(f"| {name} | {values[0]} | {values[1]} |")
        lines += ["", "| 标签 | 左侧成功率 | 右侧成功率 |", "|---|---:|---:|"]
        for tag in sorted(a["by_tag"].keys() | b["by_tag"].keys()):
            lines.append(
                f"| {cell(tag)} | "
                f"{percentage(a['by_tag'].get(tag, {}).get('success_rate'))} | "
                f"{percentage(b['by_tag'].get(tag, {}).get('success_rate'))} |"
            )
        for label, key in (("仅左侧通过", "left_wins"), ("仅右侧通过", "right_wins")):
            values = ", ".join(
                f"{cell(item['task_id'])} (repeat {item['repeat']})"
                for item in data[key]
            )
            lines += ["", f"{label}：{values or '无'}。"]
        lines.append("")
    return "\n".join(lines)
