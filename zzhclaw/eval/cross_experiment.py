"""冻结模型、任务、时间预算的跨系统对比。"""

import hashlib
import json
import os

from dotenv import load_dotenv

from .adapters import executable_identity
from .analysis import analyze_run
from .batch import benchmark_digest
from .compare import comparison_markdown
from .storage import _write_text_atomic, write_json_atomic
from .task_loader import load_benchmark


def run_cross_experiment(args, *, run_command=None):
    from .cli import main

    load_dotenv()
    model = args.model or os.getenv("OPENAI_MODEL_ID")
    if not model or not os.getenv("OPENAI_API_KEY") or not os.getenv("OPENAI_BASE_URL"):
        raise ValueError("跨系统实验需要本地 OPENAI_API_KEY / BASE_URL / MODEL_ID")
    benchmark = load_benchmark(args.benchmark, split=args.split)
    if not benchmark.tasks:
        raise ValueError("筛选后没有任务")
    identity = {
        "benchmark": benchmark.identity,
        "benchmark_digest": benchmark_digest(benchmark),
        "model": model,
        "split": args.split,
        "repeat": args.repeat,
        "task_timeout": args.task_timeout,
        "max_iterations": args.max_iterations,
        "endpoint_sha256": hashlib.sha256(
            os.environ["OPENAI_BASE_URL"].encode()
        ).hexdigest(),
        "aider": executable_identity(args.aider_executable),
    }
    root = args.output.expanduser().resolve()
    if root.is_relative_to(benchmark.root):
        raise ValueError("实验输出不能位于 benchmark 内")
    manifest = root / "cross-experiment.json"
    if args.resume:
        if not manifest.is_file() or json.loads(manifest.read_text()) != identity:
            raise ValueError("跨系统实验身份不一致，不能续跑")
    else:
        if root.exists() and any(root.iterdir()):
            raise ValueError("实验输出非空；使用 --resume 或新目录")
        write_json_atomic(manifest, identity)
    execute = run_command or main
    statuses = []
    for agent in ("zzhclaw", "aider"):
        destination = root / agent
        arguments = [
            "run",
            str(benchmark.manifest_path),
            "--output",
            str(destination),
            "--agent",
            agent,
            "--model",
            model,
            "--split",
            args.split,
            "--repeat",
            str(args.repeat),
            "--task-timeout",
            str(args.task_timeout),
            "--max-iterations",
            str(args.max_iterations),
            "--keep-workspaces",
        ]
        if agent == "aider":
            arguments += ["--aider-executable", str(args.aider_executable)]
        if args.resume and (destination / "manifest.json").exists():
            arguments += ["--resume"]
        print(
            f"跨系统实验：{agent}，split={args.split}，repeat={args.repeat}", flush=True
        )
        status = execute(arguments)
        if status not in (0, 1):
            return status
        statuses.append(status)
        analyze_run(destination)
        summary = json.loads((destination / "summary.json").read_text())
        if (
            summary["status_counts"].get("agent_error", 0)
            == summary["planned_attempts"]
        ):
            print("本组全部为 Agent 执行异常，停止后续实验；请查看 agent.log。")
            return 2
    _write_text_atomic(
        root / "comparison.md", comparison_markdown([root / "zzhclaw", root / "aider"])
    )
    print(f"跨系统对比：{root / 'comparison.md'}")
    return max(statuses)
