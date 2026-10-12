import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from zzhclaw.eval import BatchRunner, load_benchmark
from zzhclaw.eval.adapters import AgentDeadlineExceeded, SubprocessAdapter, supervised
from zzhclaw.eval.analysis import analyze_run
from zzhclaw.eval.compare import comparison_markdown
from zzhclaw.eval.recorder import TrajectoryRecorder
from zzhclaw.eval.report import generate_report
from zzhclaw.eval.runner import TaskRunner

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "benchmarks/python_basic/benchmark.json"


def test_supervised_replaces_binary_and_redacts_credentials(tmp_path):
    secret = "unit-test-secret-not-real"
    result = supervised(
        [
            sys.executable,
            "-c",
            'import os;os.write(1,b"\\xff"+os.environ["OPENAI_API_KEY"].encode())',
        ],
        cwd=tmp_path,
        env={"OPENAI_API_KEY": secret},
        output=tmp_path / "logs",
        timeout=5,
    )
    assert secret not in result and "[REDACTED]" in result
    assert "\ufffd" in result
    assert not (tmp_path / "logs/.agent-output.tmp").exists()


def test_timeout_kills_child_group_and_preserves_log(tmp_path):
    if os.name != "posix":
        pytest.skip("POSIX process groups")
    child = tmp_path / "late-write"
    script = (
        "import subprocess,sys,time;"
        f'subprocess.Popen([sys.executable,"-c",'
        f'"import time,pathlib;time.sleep(1.5);pathlib.Path({str(child)!r}).touch()"]);'
        'print("started",flush=True);time.sleep(10)'
    )
    with pytest.raises(AgentDeadlineExceeded):
        supervised(
            [sys.executable, "-c", script],
            cwd=tmp_path,
            env={},
            output=tmp_path / "logs",
            timeout=0.3,
        )
    assert "started" in (tmp_path / "logs/agent.log").read_text()
    # 等待原子进程原本会写文件的时刻，验证孙进程也已被终止。
    subprocess.run([sys.executable, "-c", "import time;time.sleep(1.5)"], check=True)
    assert not child.exists()


def test_external_timeout_survives_report_and_resume(tmp_path):
    benchmark = load_benchmark(MANIFEST)
    benchmark = replace(benchmark, tasks=(benchmark.task_by_id("python-001"),))

    class TimedOut:
        def run_task(self, task, workspace, output, recorder):
            recorder.record("agent_start")
            raise AgentDeadlineExceeded("budget")

    runner = BatchRunner(
        benchmark,
        tmp_path / "run",
        lambda _: TimedOut(),
        model="fake",
        configuration={"agent": "aider", "tool_metrics_available": False},
    )
    first = runner.run()
    summary = generate_report(tmp_path / "run")
    assert first["summary"] == summary
    assert summary["timeout_rate"] == 1 and summary["task_success_rate"] == 0
    assert summary["average_tool_calls"] is None
    assert summary["workspace_violation_rate"] is None
    assert runner.run(resume=True)["resumed"] == 1


def test_aider_uses_only_fixture_and_validator_is_authority(tmp_path, monkeypatch):
    benchmark = load_benchmark(MANIFEST)
    task = benchmark.task_by_id("python-002")
    executable = tmp_path / "aider"
    executable.touch()
    seen = {}

    def fake(command, *, cwd, env, output, timeout):
        seen.update(command=command, cwd=cwd, env=env)
        assert "--no-git" in command and "--no-auto-commits" in command
        assert "--no-restore-chat-history" in command
        for flag in (
            "--input-history-file",
            "--chat-history-file",
            "--llm-history-file",
        ):
            assert Path(command[command.index(flag) + 1]).parent == output
        assert not any("validators/" in arg or "references/" in arg for arg in command)
        (cwd / "text_utils.py").write_text(
            'def normalize_whitespace(text):\n    return " ".join(text.split())\n'
        )
        return "done"

    monkeypatch.setattr("zzhclaw.eval.adapters.supervised", fake)
    adapter = SubprocessAdapter(
        "aider", model="test-model", prompt="unused", executable=executable
    )
    result = TaskRunner(
        benchmark, tmp_path / "run", lambda _: adapter, run_id="r", model="test-model"
    ).run(task)
    assert result.status == "passed" and result.tool_calls == 0
    assert seen["command"][seen["command"].index("--model") + 1] == "openai/test-model"
    assert seen["env"]["HOME"].endswith("agent-home")


def test_external_failed_is_not_falsely_no_tool_action(tmp_path):
    benchmark = load_benchmark(MANIFEST)
    benchmark = replace(benchmark, tasks=(benchmark.task_by_id("python-001"),))

    class NoEdit:
        def run_task(self, task, workspace, output, recorder):
            recorder.record("agent_start")
            recorder.record("agent_final", result="claims success")
            return "claims success"

    root = tmp_path / "aider"
    BatchRunner(
        benchmark,
        root,
        lambda _: NoEdit(),
        model="fake",
        configuration={"agent": "aider", "tool_metrics_available": False},
    ).run()
    assert (
        analyze_run(root)["cases"][0]["diagnostic"]
        == "validation_failure_external_agent"
    )
    assert "N/A" in comparison_markdown([root, root])


def test_workspace_omits_caches_and_locks(tmp_path):
    benchmark = load_benchmark(MANIFEST)
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "keep.py").write_text("x=1")
    (fixture / "__pycache__").mkdir()
    (fixture / "__pycache__/cached.pyc").write_bytes(b"junk")
    (fixture / "keep.py.lock").touch()
    (fixture / "stale.pyc").touch()
    from zzhclaw.eval.workspace import WorkspaceManager

    task = replace(benchmark.task_by_id("python-001"), workspace=str(fixture))

    # fixture_path confinement is tested elsewhere; replace only resource lookup here.
    class Source:
        def fixture_path(self, task):
            return fixture

    with WorkspaceManager(Source(), tmp_path / "run").prepare(task) as prepared:
        assert [p.name for p in prepared.path.iterdir()] == ["keep.py"]


def test_worker_partial_events_and_final_answer_replayed(tmp_path, monkeypatch):
    benchmark = load_benchmark(MANIFEST)
    task = benchmark.task_by_id("python-001")
    output = tmp_path / "output"
    output.mkdir()
    cwd = tmp_path / "worker-cwd"
    cwd.mkdir()
    recorder = TrajectoryRecorder()

    def fake(command, **kwargs):
        request = json.loads(Path(command[-1]).read_text())
        Path(request["events"]).write_text(
            json.dumps({"sequence": 0, "event_type": "agent_start"})
            + "\n"
            + json.dumps({"sequence": 1, "event_type": "agent_final", "result": "done"})
            + "\n"
        )
        Path(request["answer"]).write_text(json.dumps({"final_answer": "done"}))
        return "stdout"

    monkeypatch.setattr("zzhclaw.eval.adapters.supervised", fake)
    result = SubprocessAdapter("zzhclaw", model="fake", prompt="system").run_task(
        task, cwd, output, recorder
    )
    assert result == "done" and len(recorder.events) == 2
