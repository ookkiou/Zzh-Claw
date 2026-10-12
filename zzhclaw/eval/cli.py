"""评测命令行；validate/report/compare 均不创建模型客户端。"""

import argparse
import hashlib
import os
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .batch import BatchRunner, benchmark_digest
from .compare import comparison_markdown
from .report import generate_report
from .storage import _write_text_atomic, write_json_atomic
from .task_loader import load_benchmark


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("必须是正整数")
    return number


def parser():
    root = argparse.ArgumentParser(
        prog="zzhclaw eval", description="受信任 Coding Agent 任务的本地评测"
    )
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("validate", "verify", "run"):
        command = sub.add_parser(name)
        command.add_argument("benchmark", help="benchmark manifest JSON 路径")
        command.add_argument("--split", choices=("train", "dev", "test"))
        command.add_argument(
            "--tag", action="append", default=[], help="可重复；须同时包含全部标签"
        )
        command.add_argument(
            "--task", action="append", default=[], help="可重复指定任务 ID"
        )
        if name == "verify":
            command.add_argument(
                "--output", type=Path, help="保存原始失败/参考通过的 JSON 验收证据"
            )
        if name == "run":
            command.add_argument("--model")
            command.add_argument(
                "--agent", choices=("zzhclaw", "aider"), default="zzhclaw"
            )
            command.add_argument("--aider-executable", type=Path)
            command.add_argument(
                "--task-timeout",
                type=positive,
                help="Agent 进程预算秒数；ZzhClaw 启用独立进程监督",
            )
            command.add_argument("--output", help="运行目录；续跑时必须指定原目录")
            command.add_argument("--repeat", type=positive, default=1)
            command.add_argument("--max-iterations", type=positive)
            command.add_argument(
                "--system-prompt", type=Path, help="替换系统提示词的 UTF-8 文件"
            )
            command.add_argument("--keep-workspaces", action="store_true")
            command.add_argument("--keep-failed-workspaces", action="store_true")
            command.add_argument("--resume", action="store_true")
            command.add_argument("--fail-fast", action="store_true")
    sub.add_parser("report").add_argument("run", type=Path)
    sub.add_parser("analyze").add_argument("run", type=Path)
    command = sub.add_parser("compare")
    command.add_argument("runs", nargs="+", type=Path)
    command.add_argument("--output", type=Path)
    command = sub.add_parser("experiment", help="同一模型、固定两份提示词的对比实验")
    command.add_argument("benchmark")
    command.add_argument("--output", required=True, type=Path)
    command.add_argument("--stage", choices=("smoke", "test"), default="smoke")
    command.add_argument("--model")
    command.add_argument("--repeat", type=positive, default=3)
    command.add_argument("--max-iterations", type=positive, default=12)
    command.add_argument("--resume", action="store_true")
    command = sub.add_parser("cross-experiment", help="同一模型对比 ZzhClaw 和 Aider")
    command.add_argument("benchmark")
    command.add_argument("--output", required=True, type=Path)
    command.add_argument("--aider-executable", required=True, type=Path)
    command.add_argument("--model")
    command.add_argument("--split", choices=("dev", "test"), default="dev")
    command.add_argument("--repeat", type=positive, default=1)
    command.add_argument("--task-timeout", type=positive, default=180)
    command.add_argument("--max-iterations", type=positive, default=12)
    command.add_argument("--resume", action="store_true")
    return root


def _run(args, benchmark):
    # 与交互模式共用模型环境变量和 .env 解析，不记录密钥。
    from zzhclaw.agent import Agent
    from zzhclaw.agent.core import DEFAULT_SYSTEM_PROMPT
    from zzhclaw.ai import LLMClient
    from zzhclaw.coding.tools.registry import get_skills_dir

    if args.resume and not args.output:
        raise ValueError("--resume 必须指定 --output")
    model = (
        args.model
        or os.getenv("OPENAI_MODEL_ID")
        or os.getenv("ANTHROPIC_MODEL_ID", "gpt-4o-mini")
    )
    prompt = (
        args.system_prompt.read_text(encoding="utf-8")
        if args.system_prompt
        else DEFAULT_SYSTEM_PROMPT
    )
    if args.max_iterations:
        benchmark = replace(
            benchmark,
            tasks=tuple(
                replace(task, max_iterations=args.max_iterations)
                for task in benchmark.tasks
            ),
        )
    endpoint = os.getenv("OPENAI_BASE_URL") or os.getenv("ANTHROPIC_BASE_URL", "")
    skills = hashlib.sha256()
    skill_root = Path(get_skills_dir())
    if skill_root.is_dir():
        for path in sorted(skill_root.rglob("*")):
            if path.is_file():
                skills.update(str(path.relative_to(skill_root)).encode())
                skills.update(path.read_bytes())
    if args.agent == "aider" and args.system_prompt:
        raise ValueError("Aider 使用自身系统提示词；不支持 --system-prompt")
    if args.agent == "aider" and not args.aider_executable:
        raise ValueError("--agent aider 必须指定 --aider-executable")
    configuration = {
        "agent": args.agent,
        "execution": "subprocess"
        if args.task_timeout or args.agent == "aider"
        else "in_process",
        "task_timeout_override": args.task_timeout,
        "tool_metrics_available": args.agent != "aider",
        "system_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "endpoint_sha256": hashlib.sha256(endpoint.encode()).hexdigest(),
        "global_skills_sha256": skills.hexdigest(),
        "max_iterations_override": args.max_iterations,
        "api_timeout": os.getenv("OPENAI_TIMEOUT", "60"),
        "api_max_retries": os.getenv("OPENAI_MAX_RETRIES", "3"),
    }
    if args.task_timeout or args.agent == "aider":
        configuration["global_skills_sha256"] = hashlib.sha256().hexdigest()
        configuration["user_home"] = "isolated_per_attempt"
    if args.agent == "aider":
        from .adapters import executable_identity

        configuration["aider"] = executable_identity(args.aider_executable)
        configuration["system_prompt_sha256"] = None
        configuration["initial_context"] = "all_fixture_source_files"
        configuration["edit_format"] = "diff"
    output = (
        args.output or f"runs/{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    )

    def factory(session_manager):
        return Agent(
            llm=LLMClient(model=model),
            session_manager=session_manager,
            system_prompt=prompt,
        )

    if args.task_timeout or args.agent == "aider":
        from .adapters import SubprocessAdapter

        def factory(session_manager):
            return SubprocessAdapter(
                args.agent,
                model=model,
                prompt=prompt,
                executable=args.aider_executable,
                timeout=args.task_timeout,
            )

    def progress(attempt, result, resumed):
        print(
            f"{attempt['task_id']} repeat={attempt['repeat']} {result.status}"
            + (" [已恢复]" if resumed else ""),
            flush=True,
        )

    outcome = BatchRunner(
        benchmark,
        output,
        factory,
        model=model,
        repeat=args.repeat,
        configuration=configuration,
        keep_workspaces=args.keep_workspaces,
        keep_failed_workspace=args.keep_failed_workspaces,
    ).run(resume=args.resume, fail_fast=args.fail_fast, on_progress=progress)
    print(f"报告：{Path(output).resolve() / 'report.md'}")
    summary = outcome["summary"]
    if outcome["interrupted"]:
        return 130
    return 0 if summary["pass_count"] == summary["planned_attempts"] else 1


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "cross-experiment":
            from .cross_experiment import run_cross_experiment

            return run_cross_experiment(args)
        if args.command == "experiment":
            from .experiment import run_experiment

            return run_experiment(args)
        if args.command in {"validate", "verify", "run"}:
            benchmark = load_benchmark(args.benchmark, split=args.split, tags=args.tag)
            selected = set(args.task)
            unknown = selected - {task.id for task in benchmark.tasks}
            if unknown:
                raise ValueError(f"未知或被筛选掉的任务: {sorted(unknown)}")
            if selected:
                benchmark = replace(
                    benchmark,
                    tasks=tuple(
                        task for task in benchmark.tasks if task.id in selected
                    ),
                )
            if not benchmark.tasks:
                raise ValueError("筛选后没有任务")
            if args.command == "run":
                return _run(args, benchmark)
            if args.command == "verify":
                from .verification import verify_benchmark

                def progress(row):
                    print(
                        f"{row['task_id']} "
                        + ("verified" if row["verified"] else "INVALID"),
                        flush=True,
                    )

                evidence = verify_benchmark(benchmark, on_progress=progress)
                if args.output:
                    write_json_atomic(args.output, evidence)
                print(
                    f"任务验收：{evidence['verified_count']}/{evidence['task_count']}"
                )
                return 0 if evidence["all_verified"] else 1
            print(
                f"有效：{benchmark.identity}，{len(benchmark.tasks)} 个任务，"
                f"sha256={benchmark_digest(benchmark)}"
            )
            print("仅检查结构、路径和资源指纹；未执行 validator 或调用模型。")
        elif args.command == "analyze":
            from .analysis import analyze_run

            evidence = analyze_run(args.run)
            print(f"失败案例：{args.run / 'failures.md'}；{evidence['case_count']} 个")
        elif args.command == "report":
            summary = generate_report(args.run)
            print(
                f"报告：{args.run / 'report.md'}；"
                f"通过 {summary['pass_count']}/{summary['planned_attempts']}"
            )
        else:
            markdown = comparison_markdown(args.runs)
            if args.output:
                _write_text_atomic(args.output, markdown)
                print(f"对比报告：{args.output}")
            else:
                print(markdown)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"评测错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
