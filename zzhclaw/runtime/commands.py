"""有界输出、可取消、清理进程组的统一命令执行器。"""

from __future__ import annotations

import math
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence

_ACTIVE_PROCESSES = set()


_ENV_ALLOWLIST = {
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "TMPDIR",
    "VIRTUAL_ENV",
    "PYTHONPATH",
    "PYTHONNOUSERSITE",
    "PYTHONDONTWRITEBYTECODE",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "SSH_AUTH_SOCK",
    "TERM",
    "NO_COLOR",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "ALL_PROXY",
    "all_proxy",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
}


def command_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """普通工具环境；模型进程所需凭据须由调用方显式传入 env。"""
    source = os.environ if source is None else source
    result = {key: value for key, value in source.items() if key in _ENV_ALLOWLIST}
    result["ZZHCLAW_PYTHON"] = sys.executable
    return result


def _secrets(*environments):
    return sorted(
        {
            value
            for env in environments
            for key, value in env.items()
            if value
            and any(
                word in key.upper()
                for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")
            )
        },
        key=len,
        reverse=True,
    )


def _redact(value, secrets):
    for secret in secrets:
        value = value.replace(secret, "[REDACTED]")
    return value


@dataclass(frozen=True)
class CommandResult:
    status: str
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    log_truncated: bool = False
    error: str | None = None

    @property
    def error_code(self):
        return {
            "succeeded": None,
            "failed": "command_failed",
            "timeout": "command_timeout",
            "cancelled": "command_cancelled",
            "spawn_error": "command_spawn_error",
            "capture_error": "command_capture_error",
        }[self.status]

    def to_dict(self):
        return {**asdict(self), "error_code": self.error_code}

    def metadata(self):
        result = self.to_dict()
        result.pop("stdout")
        result.pop("stderr")
        return result


class _Buffer:
    def __init__(self, limit, *, tail=False):
        self.limit = limit
        self.tail = tail
        self.value = bytearray()
        self.truncated = False

    def append(self, data):
        self.truncated |= len(self.value) + len(data) > self.limit
        if self.tail:
            self.value.extend(data)
            if len(self.value) > self.limit:
                del self.value[: len(self.value) - self.limit]
        else:
            self.value.extend(data[: max(0, self.limit - len(self.value))])

    def text(self, secrets):
        text = _redact(self.value.decode("utf-8", errors="replace"), secrets)
        encoded = text.encode("utf-8")
        self.truncated |= len(encoded) > self.limit
        bounded = encoded[-self.limit :] if self.tail else encoded[: self.limit]
        return bounded.decode("utf-8", errors="ignore")


def kill_active_commands():
    """worker 的 SIGTERM 处理器使用；先杀内层组，再退出外层组。"""
    for process in _ACTIVE_PROCESSES.copy():
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            elif process.poll() is None:
                process.kill()
        except ProcessLookupError:
            pass


def _cleanup(process):
    """包括普通结束留下的同组后台进程；不是恶意进程的安全隔离。"""
    if os.name != "posix":
        if process.poll() is None:
            process.kill()
        process.wait()
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def run_command(
    command: str | Sequence[str],
    *,
    cwd: str | Path,
    env: Mapping[str, str] | None = None,
    timeout: float = 30,
    shell: bool = False,
    output_limit: int = 100_000,
    log_path: str | Path | None = None,
    log_limit: int = 1_000_000,
    cancel_event: threading.Event | None = None,
) -> CommandResult:
    """同时排空两路二进制输出，有界保留前缀；可选日志保留合并输出尾部。

    日志在退出/超时/中断清理时写出并脱敏。SIGKILL 无法运行 Python 清理逻辑。
    外层监督 worker 时，worker 必须处理 SIGTERM 才能清理其独立命令组。
    """
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (float, int))
        or not math.isfinite(timeout)
        or timeout <= 0
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in (output_limit, log_limit)
        )
    ):
        raise ValueError("timeout/output_limit/log_limit 必须大于零")
    if isinstance(command, str) != shell:
        raise ValueError("字符串命令必须显式 shell=True；argv 必须 shell=False")
    if not command:
        raise ValueError("command 不能为空")
    started = time.perf_counter()
    environment = command_environment() if env is None else dict(env)
    secrets = _secrets(environment, os.environ)
    stdout, stderr = _Buffer(output_limit), _Buffer(output_limit)
    log = _Buffer(log_limit, tail=True)
    if cancel_event is not None and cancel_event.is_set():
        return CommandResult(status="cancelled")
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            shell=shell,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            start_new_session=os.name == "posix",
        )
    except OSError as exc:
        detail = _redact(f"{type(exc).__name__}: {exc}", secrets)
        if log_path is not None:
            path = Path(log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            log.append(detail.encode("utf-8"))
            path.write_text(log.text(secrets), encoding="utf-8")
        return CommandResult(
            status="spawn_error",
            error=detail,
            log_truncated=log.truncated,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    _ACTIVE_PROCESSES.add(process)
    messages = queue.Queue(maxsize=16)
    stopped = threading.Event()

    read_errors = []

    def send(name, data):
        while not stopped.is_set():
            try:
                messages.put((name, data), timeout=0.05)
                return
            except queue.Full:
                continue

    def read(pipe, name):
        try:
            while not stopped.is_set():
                data = os.read(pipe.fileno(), 16384)
                if data:
                    send(name, data)
                if not data:
                    break
        except OSError as exc:
            if not stopped.is_set():
                read_errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            send(name, b"")
            pipe.close()

    threads = [
        threading.Thread(target=read, args=(pipe, name), daemon=True)
        for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr))
    ]
    started_threads = []
    status = None
    ended = set()
    cleaned = False
    leader_finished = None
    drain_deadline = None
    try:
        for thread in threads:
            thread.start()
            started_threads.append(thread)
        while len(ended) < 2 or process.poll() is None:
            now = time.perf_counter()
            if status is None:
                if cancel_event is not None and cancel_event.is_set():
                    status = "cancelled"
                elif now - started >= timeout:
                    status = "timeout"
                if status:
                    _cleanup(process)
                    cleaned = True
                    drain_deadline = time.perf_counter() + 1
            if process.poll() is not None:
                if leader_finished is None:
                    leader_finished = now
                # 后台进程可能持有 pipe；主命令结束不允许其长期阻塞输出回收。
                if not cleaned and now - leader_finished >= 0.2:
                    _cleanup(process)
                    cleaned = True
                    drain_deadline = time.perf_counter() + 1
            if drain_deadline is not None and now > drain_deadline:
                read_errors.append("输出管道未在清理期限内关闭")
                break
            try:
                name, data = messages.get(timeout=0.02)
            except queue.Empty:
                continue
            if not data:
                ended.add(name)
            else:
                (stdout if name == "stdout" else stderr).append(data)
                if log_path is not None:
                    log.append(data)
        status = status or ("succeeded" if process.returncode == 0 else "failed")
    finally:
        if not cleaned:
            _cleanup(process)
        _ACTIVE_PROCESSES.discard(process)
        stopped.set()
        for thread in started_threads:
            thread.join(timeout=1)
        if read_errors:
            detail = ("\n输出读取异常: " + "; ".join(read_errors)).encode("utf-8")
            stderr.append(detail)
            log.append(detail)
        if log_path is not None:
            path = Path(log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(log.text(secrets), encoding="utf-8")
    if read_errors:
        status = "capture_error" if status == "succeeded" else status
    return CommandResult(
        status=status,
        exit_code=None if status in {"timeout", "cancelled"} else process.returncode,
        stdout=stdout.text(secrets),
        stderr=stderr.text(secrets),
        duration_ms=int((time.perf_counter() - started) * 1000),
        stdout_truncated=stdout.truncated,
        stderr_truncated=stderr.truncated,
        log_truncated=log.truncated,
        error=_redact("; ".join(read_errors), secrets) if read_errors else None,
    )
