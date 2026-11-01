"""Explicit CLI for the optional, externally provided repair runtime."""

import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the restricted dev code-repair profile")
    parser.add_argument("--public-data", type=Path, required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--model", default="zzh-repair-step70")
    parser.add_argument("--inference-url", default="http://127.0.0.1:18000")
    parser.add_argument("--evaluator-url", default="http://127.0.0.1:8765")
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        from code_repair.evaluation import RemoteEvaluator
        from code_repair.public_data import load_public_task
    except ModuleNotFoundError:
        parser.error("Add the pinned agent-r1 repository to PYTHONPATH; no runtime is bundled")
    from .repair import CodeRepairAgent, VllmRepairTransport
    from ..coding.session import SessionManager

    if args.output.exists():
        parser.error("Output already exists; preserve earlier experiment evidence")
    manifest = json.loads((args.public_data / "manifest.json").read_text())
    rows = [row for row in manifest["tasks"] if row["task_id"] == args.task]
    if len(rows) != 1 or rows[0]["split"] != "dev":
        parser.error("Only dev tasks are allowed in the application integration profile")
    task = load_public_task(args.public_data, args.task)
    token = args.token_file.read_text().strip()
    evaluator = RemoteEvaluator(args.evaluator_url, token, task.task_id)
    health = evaluator.health()
    if (health.get("backend") != "docker" or not health.get("container_isolation_configured")
            or manifest["source_manifest_sha256"] not in health.get("dataset_manifest_sha256", [])):
        parser.error("Expected the matching isolated Docker evaluator")
    transport = VllmRepairTransport(args.inference_url, args.model, seed=args.seed)
    agent = CodeRepairAgent(task, evaluator, transport, task_split=rows[0]["split"],
        session_manager=SessionManager(str(args.output.parent / "sessions")))
    print(agent.run())
    content = json.dumps(agent.last_result, ensure_ascii=False, indent=2) + "\n"
    if token in content:
        raise ValueError("Credential in report")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(content)
    return 0
