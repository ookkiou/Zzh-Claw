"""真实本地子进程验证资源边界；不依赖模型或网络。"""

import json
import os
import shlex
import sys
import threading
import tracemalloc
from pathlib import Path

import pytest

from zzhclaw.runtime import command_environment, run_command


def python(script):
    return [sys.executable, "-c", script]


def test_states_and_binary_output(tmp_path):
    result = run_command(
        python("import os;os.write(1,b'\\xffok');os.write(2,b'err');exit(7)"),
        cwd=tmp_path,
    )
    assert result.status == "failed" and result.exit_code == 7
    assert result.error_code == "command_failed"
    assert result.stdout == "\ufffdok" and result.stderr == "err"
    missing = run_command(["not-a-real-executable-zzhclaw"], cwd=tmp_path)
    assert (
        missing.status == "spawn_error" and missing.error_code == "command_spawn_error"
    )
    success = run_command(python("print('ok')"), cwd=tmp_path)
    assert success.status == "succeeded" and success.error_code is None


def test_large_dual_output_has_bounded_parent_memory_and_log(tmp_path):
    log = tmp_path / "command.log"
    tracemalloc.start()
    try:
        result = run_command(
            python(
                "import os;"
                "[(os.write(1,b'x'*16384),os.write(2,b'y'*16384)) for _ in range(512)]"
            ),
            cwd=tmp_path,
            output_limit=4096,
            log_path=log,
            log_limit=8192,
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result.status == "succeeded"
    assert result.stdout == "x" * 4096 and result.stderr == "y" * 4096
    assert result.stdout_truncated and result.stderr_truncated and result.log_truncated
    assert log.stat().st_size <= 8192
    assert peak < 4_000_000, f"bounded capture peak: {peak}"


def test_default_tool_environment_excludes_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-llm-credential")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake-cloud-credential")
    monkeypatch.setenv("GITHUB_TOKEN", "fake-github-credential")
    result = run_command(
        python(
            "import os,json;print(json.dumps({k:os.getenv(k) for k in "
            "['OPENAI_API_KEY','AWS_SECRET_ACCESS_KEY','GITHUB_TOKEN','PATH','ZZHCLAW_PYTHON']}))"
        ),
        cwd=tmp_path,
    )
    env = json.loads(result.stdout)
    assert (
        env["OPENAI_API_KEY"]
        is env["AWS_SECRET_ACCESS_KEY"]
        is env["GITHUB_TOKEN"]
        is None
    )
    assert env["PATH"] == os.environ["PATH"]
    assert "PYTHONPATH" in command_environment({"PYTHONPATH": "fixture"})
    assert command_environment()["ZZHCLAW_PYTHON"] == sys.executable


def test_explicit_model_env_and_split_chunk_secret_redaction(tmp_path):
    secret = "fake-api-key-crossing-read-boundaries"
    result = run_command(
        python(
            "import os;os.write(1,b'x'*16380+"
            "os.environ['OPENAI_API_KEY'].encode()+b'z'*100)"
        ),
        cwd=tmp_path,
        env={"OPENAI_API_KEY": secret},
        output_limit=20000,
        log_path=tmp_path / "agent.log",
        log_limit=20000,
    )
    assert secret not in result.stdout and "[REDACTED]" in result.stdout
    assert secret not in (tmp_path / "agent.log").read_text()


@pytest.mark.parametrize("mode", ["timeout", "cancel", "normal"])
def test_cleanup_prevents_late_background_writes(tmp_path, mode):
    if os.name != "posix":
        pytest.skip("POSIX process group guarantee")
    late = tmp_path / "late"
    background = (
        "import time,pathlib;time.sleep(1.2);pathlib.Path("
        + repr(str(late))
        + ").touch()"
    )
    script = (
        "import subprocess,sys,time;"
        f"subprocess.Popen([sys.executable,'-c',"
        f"{background!r}]);"
        "print('started',flush=True);" + ("time.sleep(10)" if mode != "normal" else "")
    )
    cancel = threading.Event()
    timer = threading.Timer(0.2, cancel.set)
    if mode == "cancel":
        timer.start()
    try:
        result = run_command(
            python(script),
            cwd=tmp_path,
            timeout=0.2 if mode == "timeout" else 5,
            cancel_event=cancel if mode == "cancel" else None,
        )
    finally:
        if mode == "cancel":
            timer.cancel()
            timer.join()
    assert (
        result.status
        == {"timeout": "timeout", "cancel": "cancelled", "normal": "succeeded"}[mode]
    )
    assert "started" in result.stdout
    run_command(python("import time;time.sleep(1.3)"), cwd=tmp_path)
    assert not late.exists()


def test_worker_outer_timeout_cleans_nested_tool_process_group(tmp_path):
    if os.name != "posix":
        pytest.skip("POSIX worker termination")
    root = Path(__file__).resolve().parents[1]
    late = tmp_path / "nested-late"
    ready = tmp_path / "nested-ready"
    nested = python(
        "import time,pathlib;pathlib.Path(" + repr(str(ready)) + ").touch();"
        "time.sleep(2.5);pathlib.Path(" + repr(str(late)) + ").touch()"
    )
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            dict(
                model="fake",
                workspace=str(tmp_path),
                system_prompt="",
                sessions=str(tmp_path / "sessions"),
                events=str(tmp_path / "events.jsonl"),
                answer=str(tmp_path / "answer.json"),
                prompt="test",
                max_iterations=1,
            )
        )
    )
    script = (
        "import sys;from zzhclaw.eval import worker;"
        "from zzhclaw.runtime import run_command;"
        "worker.LLMClient=lambda **kwargs:None;"
        f"worker.Agent=type('FakeAgent',(),{{'__init__':lambda self,**kwargs:None,"
        f"'run':lambda *args,**kwargs:run_command({nested!r},"
        f"cwd={str(tmp_path)!r},timeout=10)}});"
        f"sys.argv=['worker',{str(request)!r}];worker.main()"
    )
    env = command_environment()
    env["PYTHONPATH"] = str(root)
    result = run_command(python(script), cwd=tmp_path, env=env, timeout=1.5)
    assert result.status == "timeout" and ready.exists()
    run_command(python("import time;time.sleep(2.6)"), cwd=tmp_path)
    assert not late.exists()


def test_prescheduled_cancel_does_not_spawn(tmp_path):
    cancel = threading.Event()
    cancel.set()
    assert (
        run_command(["missing"], cwd=tmp_path, cancel_event=cancel).status
        == "cancelled"
    )


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True])
def test_invalid_deadline_rejected(tmp_path, timeout):
    with pytest.raises(ValueError):
        run_command(python("pass"), cwd=tmp_path, timeout=timeout)


def test_shell_is_explicit_and_literal_argv_not_interpreted(tmp_path):
    with pytest.raises(ValueError):
        run_command("echo unsafe", cwd=tmp_path)
    marker = tmp_path / "must-not-exist"
    result = run_command(
        python("import sys;print(sys.argv[1])") + [f"$(touch {marker})"], cwd=tmp_path
    )
    assert result.status == "succeeded" and not marker.exists()
    result = run_command("printf shell-ok", cwd=tmp_path, shell=True)
    assert result.stdout == "shell-ok"


def test_run_bash_binary_and_structured_nonzero(workspace):
    from zzhclaw.coding.tools import run_bash

    result = run_bash(shlex.join(python("import os;os.write(1,b'\\xff');exit(3)")))
    assert "\ufffd" in result and "(退出码: 3)" in result
    assert result.error_code == "command_failed"
    assert result.metadata["command"]["exit_code"] == 3


def test_spawn_error_log_respects_utf8_byte_limit(tmp_path):
    result = run_command(
        [str(tmp_path / ("不存在" * 30))],
        cwd=tmp_path,
        log_path=tmp_path / "failure.log",
        log_limit=80,
    )
    assert result.status == "spawn_error" and result.log_truncated
    assert (tmp_path / "failure.log").stat().st_size <= 80
