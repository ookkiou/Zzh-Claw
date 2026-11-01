"""分别运行目标测试与冻结回归，明确验证目标包来源。"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASKS = {f"repo-{number:03d}" for number in range(1, 7)}
SUPERSEDED = "test_fork_inherits_summary_clamped_to_fork_point"


def worker(workspace, task, phase):
    sys.path[:0] = [str(workspace), str(ROOT / "regression")]
    os.chdir(workspace)
    # 验收不加载本机 .env。测试需要的假凭据由 monkeypatch 显式设置。
    import dotenv

    dotenv.load_dotenv = lambda *args, **kwargs: False
    import zzhclaw

    if not Path(zzhclaw.__file__).resolve().is_relative_to(workspace):
        raise RuntimeError("validator imported host package instead of task workspace")
    import pytest

    args = [
        "-c",
        str(ROOT / "pytest.ini"),
        "--confcutdir",
        str(ROOT),
        "--import-mode=importlib",
        "-q",
        "-p",
        "no:cacheprovider",
    ]
    if phase == "target":
        args += [str(ROOT / "targets" / f"test_{task.replace('-', '_')}.py")]
    else:
        args += [str(ROOT / "regression")]
        if task == "repo-006":
            args += ["-k", f"not {SUPERSEDED}"]
    return int(pytest.main(args))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True, choices=sorted(TASKS))
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--worker", choices=("target", "regression"))
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    if args.worker:
        return worker(workspace, args.task, args.worker)
    codes = {}
    for phase in ("target", "regression"):
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--task",
                    args.task,
                    "--workspace",
                    str(workspace),
                    "--worker",
                    phase,
                ],
                cwd=workspace,
                env=os.environ.copy(),
                timeout=40,
                check=False,
            )
            codes[phase] = result.returncode
        except subprocess.TimeoutExpired:
            codes[phase] = "timeout"
    print(
        "ZZHCLAW_REPO_VALIDATION " + json.dumps({"task": args.task, **codes}),
        flush=True,
    )
    # 原始代码若连原有回归都未通过，不把它算作有效的任务失败。
    if codes["regression"] != 0 or codes["target"] not in (0, 1):
        return 2
    return codes["target"]


if __name__ == "__main__":
    raise SystemExit(main())
