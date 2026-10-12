"""受监督的 CLI Agent 适配器；外部进程的内部指标保持未知。"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Protocol

from .models import TraceEvent
from .storage import write_json_atomic


class AgentDeadlineExceeded(TimeoutError):
    """Agent 进程超过本次任务的时间预算。"""


class AgentAdapter(Protocol):
    def run_task(self, task, workspace: Path, output: Path, recorder) -> str: ...


def _stop(process):
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()
    process.wait()


def supervised(command, *, cwd, env, output, timeout):
    """禁用 shell；超时/中断终止进程组，日志落盘而非无限缓存在内存。"""
    output.mkdir(parents=True, exist_ok=True)
    raw = output / ".agent-output.tmp"
    timed_out = False
    try:
        with raw.open("wb") as stream:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=subprocess.STDOUT,
                start_new_session=os.name == "posix",
            )
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                _stop(process)
            except BaseException:
                _stop(process)
                raise
    finally:
        if raw.exists():
            with raw.open("rb") as stream:
                stream.seek(0, 2)
                size = stream.tell()
                stream.seek(max(0, size - 1_000_000))
                log = stream.read().decode("utf-8", errors="replace")
            for key, value in env.items():
                if value and any(
                    word in key for word in ("API_KEY", "TOKEN", "SECRET")
                ):
                    log = log.replace(value, "[REDACTED]")
            (output / "agent.log").write_text(log, encoding="utf-8")
            raw.unlink()
    if timed_out:
        raise AgentDeadlineExceeded(f"Agent 超过 {timeout} 秒预算，已终止进程组")
    if process.returncode:
        raise RuntimeError(f"Agent 进程退出码 {process.returncode}；查看 agent.log")
    return log[-16000:]


class SubprocessAdapter:
    """ZzhClaw worker 或 Aider CLI；二者接受同一任务并由外部验收。"""

    def __init__(self, name, *, model, prompt, executable=None, timeout=None):
        if name not in {"zzhclaw", "aider"}:
            raise ValueError(f"不支持的 Agent: {name}")
        self.name = name
        self.model = model
        self.prompt = prompt
        self.executable = str(Path(executable).resolve()) if executable else None
        self.timeout = timeout

    def run_task(self, task, workspace, output, recorder):
        timeout = self.timeout or task.task_timeout_seconds or 180
        env = {
            key: value
            for key, value in os.environ.items()
            if key
            in {
                "PATH",
                "LANG",
                "LC_ALL",
                "SYSTEMROOT",
                "SSL_CERT_FILE",
                "SSL_CERT_DIR",
                "HTTPS_PROXY",
                "HTTP_PROXY",
                "NO_PROXY",
            }
            or key.startswith(("OPENAI_", "ANTHROPIC_"))
        }
        # HOME / dotenv / user config 均定向独立目录；凭据只通过子进程环境传递。
        home = output / "agent-home"
        home.mkdir(exist_ok=True)
        env.update(HOME=str(home), PYTHONDONTWRITEBYTECODE="1", NO_COLOR="1")
        request = output / "agent-request.json"
        events = output / "worker-events.jsonl"
        answer = output / "worker-answer.json"
        if self.name == "zzhclaw":
            write_json_atomic(
                request,
                {
                    "model": self.model,
                    "prompt": task.prompt,
                    "system_prompt": self.prompt,
                    "workspace": str(workspace),
                    "max_iterations": task.max_iterations,
                    "events": str(events),
                    "answer": str(answer),
                    "sessions": str(output / "sessions"),
                },
            )
            # 不允许残留轨迹用于重跑。
            events.unlink(missing_ok=True)
            answer.unlink(missing_ok=True)
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
            command = [sys.executable, "-m", "zzhclaw.eval.worker", str(request)]
        else:
            if not self.executable or not Path(self.executable).is_file():
                raise ValueError("Aider 可执行文件不存在；使用 --aider-executable 指定")
            prompt_file = output / "task-prompt.txt"
            prompt_file.write_text(task.prompt, encoding="utf-8")
            config = output / "aider.yml"
            config.write_text("{}\n", encoding="utf-8")
            dotenv = output / "empty.env"
            dotenv.write_text("", encoding="utf-8")
            model_settings = output / "aider-model-settings.yml"
            model_settings.write_text("[]\n", encoding="utf-8")
            model_metadata = output / "aider-model-metadata.json"
            model_metadata.write_text("{}\n", encoding="utf-8")
            env["OPENAI_API_BASE"] = env.get("OPENAI_BASE_URL", "")
            model = (
                self.model
                if self.model.startswith("openai/")
                else f"openai/{self.model}"
            )
            command = [
                self.executable,
                "--model",
                model,
                "--weak-model",
                model,
                "--config",
                str(config),
                "--env-file",
                str(dotenv),
                "--model-settings-file",
                str(model_settings),
                "--model-metadata-file",
                str(model_metadata),
                "--input-history-file",
                str(output / "aider-input.history"),
                "--chat-history-file",
                str(output / "aider-chat.history.md"),
                "--llm-history-file",
                str(output / "aider-llm.history"),
                "--no-restore-chat-history",
                "--message-file",
                str(prompt_file),
                "--yes-always",
                "--no-git",
                "--no-auto-commits",
                "--no-dirty-commits",
                "--no-stream",
                "--no-check-update",
                "--no-show-release-notes",
                "--no-analytics",
                "--no-auto-lint",
                "--no-auto-test",
                "--no-detect-urls",
                "--no-suggest-shell-commands",
                "--edit-format",
                "diff",
                "--encoding",
                "utf-8",
                "--timeout",
                str(timeout),
            ]
            # 固定全部任务源码作为初始可编辑上下文，记录在方法说明中。
            command += [
                str(p.relative_to(workspace))
                for p in sorted(workspace.rglob("*"))
                if p.is_file() and p.suffix in {".py", ".toml", ".json", ".md"}
            ]
            recorder.record(
                "agent_start",
                metadata={
                    "agent": "aider",
                    "tool_metrics_available": False,
                    "timeout_seconds": timeout,
                },
            )
        try:
            log = supervised(
                command, cwd=workspace, env=env, output=output, timeout=timeout
            )
        finally:
            if self.name == "zzhclaw" and events.exists():
                # 最后一行可能在终止时写了一半；只接收完整且连续的事件。
                for index, line in enumerate(events.read_text().splitlines()):
                    try:
                        event = TraceEvent.from_dict(json.loads(line))
                    except (ValueError, TypeError, KeyError):
                        break
                    if event.sequence != index:
                        raise ValueError("worker 轨迹序号不连续")
                    data = event.to_dict()
                    data.pop("sequence")
                    data["metadata"]["worker_timestamp"] = data.pop("timestamp")
                    recorder(data)
        if self.name == "zzhclaw":
            return json.loads(answer.read_text())["final_answer"]
        recorder.record("agent_final", result=log, metadata={"agent": "aider"})
        return log


def executable_identity(path):
    """固定 Aider 版本和启动文件内容用于断点续跑身份检查。"""
    executable = Path(path).expanduser().resolve()
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("无法读取 Aider 版本；请检查 --aider-executable") from exc
    return {
        "executable": str(executable),
        "version": result.stdout.strip(),
        "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
    }
