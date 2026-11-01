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


def number(value):
    return "N/A" if value is None else f"{value:.8g}"


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
    for name in (
        "input_tokens",
        "output_tokens",
        "request_count",
        "request_duration_ms",
        "requests_with_usage",
        "estimated_cost",
        "average_successful_input_tokens",
        "average_successful_output_tokens",
        "average_successful_request_count",
        "average_successful_request_duration_ms",
        "average_successful_estimated_cost",
    ):
        lines.append(f"| {name} | {number(summary[name])} |")
    lines += [
        f"| 估算成本币种 | {cell(summary['currency'] or 'N/A')} |",
        "| 成功任务估算成本币种 | "
        f"{cell(summary['successful_cost_currency'] or 'N/A')} |",
        f"| token 完整的 attempt | {summary['token_usage_attempts']} / "
        f"{summary['observed_usage_attempts']} |",
        f"| 成本完整的 attempt | {summary['priced_attempts']} / "
        f"{summary['observed_usage_attempts']} |",
    ]
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
        "| Task | Repeat | 状态 | 工具次数 | 请求次数 | 输入 token | 输出 token "
        "| 请求耗时 ms | 估算成本 | 币种 | 错误 |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in records:
        result = row["result"]
        lines.append(
            f"| {cell(result.task_id)} | {row['repeat']} | {result.status} | "
            f"{result.tool_calls if summary['tool_metrics_available'] else 'N/A'} | "
            f"{number(result.usage.request_count)} | "
            f"{number(result.usage.input_tokens)} | "
            f"{number(result.usage.output_tokens)} | "
            f"{number(result.usage.request_duration_ms)} | "
            f"{number(result.usage.estimated_cost)} | "
            f"{cell(result.usage.currency or 'N/A')} | "
            f"{cell(result.error or '')} |"
        )
    lines += [
        "",
        "## 解释范围",
        "",
        "成功率以已完成的有效 attempt 为分母，包含基础设施失败；"
        "中断 attempt 不计入分母。未完成运行不应作为最终能力结论。",
        "外部 Agent 未观测的工具调用、迭代和安全指标显示 N/A。",
        "新轨迹优先使用结构化错误码；旧轨迹的工具错误和安全计数依赖结果字符串，是诊断近似值。"
        "token 缺失显示为 N/A，不以字符数代替。",
        "请求次数按 SDK create 调用计数，包含摘要及失败请求；"
        "SDK 内部 HTTP 重试不单独计数。"
        "请求耗时包含 SDK 重试等待及完整流消费，不包含工具或 Validator 时间。"
        "每次请求的开始/结束、用途、状态、模型、usage 与单价快照见 trace.jsonl。",
        "token、请求和费用总量覆盖所有已保存 attempt（含中断）；"
        "成功任务均值仅统计 passed。"
        "任一请求或 attempt 缺失 usage 时，对应完整总量为 N/A；覆盖度单独列出。"
        "尚未结束的请求耗时未知，不填零。未完成的计划任务尚无费用记录。",
        "估算成本 =（输入 token × 输入每百万单价 "
        "+ 输出 token × 输出每百万单价）/ 1000000。"
        "未配置单价或混合币种时总费用为 N/A；不含缓存差价、优惠、税费等账单规则。",
        "观测 pass@k 表示这 k 次中至少成功一次的比例，不是更大采样池上的无偏估计。",
        "本地工作区副本不提供容器级隔离，当前仅适合受信任任务。",
        "",
    ]
    write_json_atomic(root / "summary.json", summary)
    _write_text_atomic(root / "report.md", "\n".join(lines))
    return summary
