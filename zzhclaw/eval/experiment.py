"""固定同一模型的 baseline/candidate 提示词对比实验。"""

import hashlib
import json
import os

from dotenv import load_dotenv

from .analysis import analyze_run
from .batch import benchmark_digest
from .compare import comparison_markdown
from .storage import _write_text_atomic, write_json_atomic
from .task_loader import load_benchmark


def run_experiment(args, *, run_command=None):
    from .cli import main

    load_dotenv()
    key = os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    endpoint = os.getenv("OPENAI_BASE_URL") or os.getenv("ANTHROPIC_BASE_URL")
    if not key or key == "your-api-key-here" or not endpoint:
        raise ValueError(
            "模型配置不完整；请在本地 .env 填写 API_KEY、BASE_URL、MODEL_ID，"
            "不要发送密钥到聊天"
        )
    model = (
        args.model or os.getenv("OPENAI_MODEL_ID") or os.getenv("ANTHROPIC_MODEL_ID")
    )
    if not model:
        raise ValueError("实验必须显式配置模型 ID（--model 或 MODEL_ID）")
    execute = run_command or main
    benchmark = load_benchmark(args.benchmark)
    prompts = {
        name: benchmark.root / "prompts" / f"{name}.txt"
        for name in ("baseline", "candidate")
    }
    configuration = {
        "benchmark": benchmark.identity,
        "benchmark_digest": benchmark_digest(benchmark),
        "stage": args.stage,
        "model": model,
        "max_iterations": args.max_iterations,
        "repeat": 1 if args.stage == "smoke" else args.repeat,
        "prompts": {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in prompts.items()
        },
    }
    if args.stage == "smoke":
        for task_id in ("python-001", "python-009"):
            if benchmark.task_by_id(task_id).split != "dev":
                raise ValueError("smoke 任务必须来自 dev 集")
    root = args.output.expanduser().resolve()
    if root.is_relative_to(benchmark.root):
        raise ValueError("实验输出不能位于 benchmark 内")
    manifest = root / "experiment.json"
    if args.resume:
        if not manifest.is_file() or json.loads(manifest.read_text()) != configuration:
            raise ValueError("实验配置不匹配，不能续跑；请使用新的输出目录")
    else:
        if root.exists() and any(root.iterdir()):
            raise ValueError("实验输出目录非空；使用 --resume 或新目录")
        write_json_atomic(manifest, configuration)
    statuses = []
    for name, prompt in prompts.items():
        destination = root / name
        arguments = [
            "run",
            str(benchmark.manifest_path),
            "--output",
            str(destination),
            "--model",
            model,
            "--system-prompt",
            str(prompt),
            "--repeat",
            str(configuration["repeat"]),
            "--max-iterations",
            str(args.max_iterations),
            "--keep-workspaces",
        ]
        if args.stage == "smoke":
            arguments += [
                "--split",
                "dev",
                "--task",
                "python-001",
                "--task",
                "python-009",
            ]
        else:
            arguments += ["--split", "test"]
        if args.resume and (destination / "manifest.json").is_file():
            arguments += ["--resume"]
        print(f"实验 {args.stage}: {name}，模型 {model}", flush=True)
        status = execute(arguments)
        if status not in (0, 1):
            return status
        analyze_run(destination)
        summary = json.loads((destination / "summary.json").read_text())
        if (
            summary["status_counts"].get("agent_error", 0)
            + summary["status_counts"].get("validator_error", 0)
            == summary["planned_attempts"]
        ):
            print(
                "本组全部为模型/执行/验收基础设施异常，已停止后续实验；请先检查失败报告。"
            )
            return 2
        statuses.append(status)
    _write_text_atomic(
        root / "comparison.md", comparison_markdown([root / name for name in prompts])
    )
    print(f"实验对比：{root / 'comparison.md'}")
    return max(statuses)
