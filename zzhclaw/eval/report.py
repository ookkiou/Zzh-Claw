"""从磁盘产物重建汇总报告，不依赖模型 API。"""

from __future__ import annotations

import json
from pathlib import Path

from .batch import read_attempt
from .metrics import aggregate
from .models import TraceEvent
from .storage import _write_text_atomic, write_json_atomic


def load_run(root):
    root = Path(root).expanduser().resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("schema_version") != 1:
        raise ValueError("不支持的 run schema_version")
    records = []
    for item in manifest["schedule"]:
        directory = (root / item["directory"]).resolve()
        if not directory.is_relative_to(root):
            raise ValueError("运行产物路径越界")
        if not (directory / "result.json").exists():
            continue
        result = read_attempt(directory, manifest=manifest, task_id=item["task_id"])
        events = [
            TraceEvent.from_dict(json.loads(line))
            for line in (directory / "trace.jsonl").read_text().splitlines()
            if line.strip()
        ]
        records.append({"repeat": item["repeat"], "result": result, "events": events})
    return manifest, records


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def percentage(value):
    return "N/A" if value is None else f"{value:.1%}"


def generate_report(root):
    root = Path(root).expanduser().resolve()
    manifest, records = load_run(root)
    summary = aggregate(records, manifest)
    lines = [
        f"# Eval 报告：{cell(manifest['run_id'])}",
        "",
        f"Benchmark：{cell(manifest['benchmark'])}；模型：{cell(manifest['model'])}",
        "",
        f"完成 {summary['completed_attempts']}/{summary['planned_attempts']} 次；"
        f"待完成 {summary['pending_attempts']} 次。",
        "",
        "| 指标 | 结果 |",
        "|---|---|",
        f"| 任务成功率 | {percentage(summary['task_success_rate'])} |",
        f"| 通过次数 | {summary['pass_count']} |",
    ]
    for name in ("average_tool_calls", "average_iterations", "average_latency_ms"):
        value = summary[name]
        lines.append(f"| {name} | {'N/A' if value is None else f'{value:.2f}'} |")
    for name in ("input_tokens", "output_tokens"):
        lines.append(
            f"| {name} | {summary[name] if summary[name] is not None else 'N/A'} |"
        )
    for name in (
        "timeout_rate",
        "invalid_tool_rate",
        "tool_error_rate",
        "repeated_tool_rate",
        "workspace_violation_rate",
        "dangerous_command_rejection_rate",
        "max_iteration_rate",
    ):
        lines.append(f"| {name} | {percentage(summary[name])} |")
    lines += ["", "## 按标签", "", "| 标签 | 次数 | 成功率 |", "|---|---:|---:|"]
    for tag, value in summary["by_tag"].items():
        lines.append(
            f"| {cell(tag)} | {value['attempts']} | "
            f"{percentage(value['success_rate'])} |"
        )
    lines += [
        "",
        "## 重复运行",
        "",
        f"k={summary['repeat']}，完成全部 k 次的任务数："
        f"{summary['fully_repeated_tasks']}。",
        f"观测 pass@k：{percentage(summary['observed_pass_at_k'])}；"
        f"consistency@k：{percentage(summary['consistency_at_k'])}。",
        "",
        "## 逐次结果",
        "",
        "| Task | Repeat | 状态 | 工具次数 | 错误 |",
        "|---|---:|---|---:|---|",
    ]
    for row in records:
        result = row["result"]
        lines.append(
            f"| {cell(result.task_id)} | {row['repeat']} | {result.status} | "
            f"{result.tool_calls if summary['tool_metrics_available'] else 'N/A'} | "
            f"{cell(result.error or '')} |"
        )
    lines += [
        "",
        "## 解释范围",
        "",
        "成功率以已完成的有效 attempt 为分母，包含基础设施失败；"
        "中断 attempt 不计入分母。未完成运行不应作为最终能力结论。",
        "外部 Agent 未观测的工具调用、迭代和安全指标显示 N/A。",
        "工具错误和安全计数部分依赖结果字符串，是诊断近似值。"
        "token 缺失显示为 N/A，不以字符数代替。",
        "观测 pass@k 表示这 k 次中至少成功一次的比例，不是更大采样池上的无偏估计。",
        "本地工作区副本不提供容器级隔离，当前仅适合受信任任务。",
        "",
    ]
    write_json_atomic(root / "summary.json", summary)
    _write_text_atomic(root / "report.md", "\n".join(lines))
    return summary
