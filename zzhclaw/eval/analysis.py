"""依据已有轨迹生成失败案例；分类只作诊断提示。"""

from collections import Counter
from pathlib import Path

from .report import cell, load_run
from .storage import _write_text_atomic, write_json_atomic


def analyze_run(root):
    root = Path(root).expanduser().resolve()
    manifest, rows = load_run(root)
    cases = []
    for row in rows:
        result = row["result"]
        if result.status == "passed":
            continue
        if result.status != "failed":
            category = result.status
        elif any(
            event.event_type == "agent_final"
            and event.metadata.get("termination") == "max_iterations"
            for event in row["events"]
        ):
            category = "iteration_limit"
        elif not manifest.get("configuration", {}).get("tool_metrics_available", True):
            category = "validation_failure_external_agent"
        elif result.tool_calls == 0:
            category = "no_tool_action"
        elif any(
            event.event_type == "tool_result"
            and (event.error or (event.result or "").startswith(("错误:", "未知工具:")))
            for event in row["events"]
        ):
            category = "tool_error_observed"
        else:
            category = "validation_failure"
        cases.append(
            {
                "task_id": result.task_id,
                "repeat": row["repeat"],
                "status": result.status,
                "diagnostic": category,
                "error": result.error,
                "final_answer": result.final_answer[:2000],
                "validator_output_tail": (
                    result.validator.stdout + "\n" + result.validator.stderr
                )[-4000:],
                "last_tools": [
                    event.tool_name
                    for event in row["events"]
                    if event.event_type == "tool_call"
                ][-5:],
                "trace": f"attempts/repeat-{row['repeat']:03d}/tasks/"
                f"{result.task_id}/trace.jsonl",
            }
        )
    evidence = {
        "run_id": manifest["run_id"],
        "case_count": len(cases),
        "diagnostic_counts": dict(Counter(case["diagnostic"] for case in cases)),
        "cases": cases,
    }
    lines = [
        f"# 失败诊断：{cell(manifest['run_id'])}",
        "",
        "分类由状态与轨迹规则产生，是待核实的诊断线索，不等同于已确认根因。",
        "",
        f"保存 {len(cases)} 个非通过案例。",
        "",
    ]
    for case in cases:
        lines += [
            f"## {cell(case['task_id'])} / repeat {case['repeat']}",
            "",
            f"状态：{case['status']}；诊断：{case['diagnostic']}。",
            f"最后的工具：{cell(', '.join(case['last_tools'])) or '无'}。",
            f"轨迹：[{cell(case['task_id'])}]({case['trace']})",
            "",
            f"异常：{cell(case['error'] or '无')}。",
            "",
            "最终回答：",
            "",
        ]
        # 使用缩进代码块，避免输出中出现 Markdown fence 破坏报告。
        lines += [
            "    " + line for line in (case["final_answer"] or "（空）").splitlines()
        ]
        lines += ["", "验收输出末尾：", ""]
        lines += [
            "    " + line
            for line in (case["validator_output_tail"].strip() or "（空）").splitlines()
        ]
        lines += [
            "",
            "人工复核：对照任务契约、修改后的代码和完整轨迹确认原因，再提出改进；"
            "不要直接用 test 集调提示词。",
            "",
        ]
    write_json_atomic(root / "failures.json", evidence)
    _write_text_atomic(root / "failures.md", "\n".join(lines))
    return evidence
