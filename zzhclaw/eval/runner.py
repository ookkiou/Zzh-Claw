"""ZzhClaw-Eval 的单任务执行闭环。"""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Optional

from zzhclaw.agent import Agent
from zzhclaw.coding.session import SessionManager
from zzhclaw.coding.tools import get_cwd, get_sandbox, set_cwd, set_sandbox

from .adapters import AgentDeadlineExceeded
from .evaluator import ExternalValidator
from .models import (
    EvalTask,
    SafetyMetrics,
    TaskRunResult,
    UsageMetrics,
    ValidatorResult,
    utc_now_iso,
)
from .recorder import TrajectoryRecorder
from .storage import write_json_atomic
from .task_loader import LoadedBenchmark
from .workspace import PreparedWorkspace, WorkspaceManager

AgentFactory = Callable[[SessionManager], Agent]


@contextmanager
def _active_tool_workspace(path: Path) -> Iterator[None]:
    previous_cwd = get_cwd()
    previous_sandbox = get_sandbox()
    resolved = set_cwd(str(path))
    if resolved.startswith("错误:"):
        raise RuntimeError(resolved)
    set_sandbox(True)
    try:
        yield
    finally:
        set_cwd(previous_cwd)
        set_sandbox(previous_sandbox)


class TaskRunner:
    """运行一个 EvalTask，正常完成或可捕获中断时保存结果。"""

    def __init__(
        self,
        benchmark: LoadedBenchmark,
        run_root: str | Path,
        agent_factory: AgentFactory,
        *,
        run_id: str,
        model: str,
        keep_failed_workspace: bool = False,
        keep_workspaces: bool = False,
        validator: Optional[ExternalValidator] = None,
    ):
        self.benchmark = benchmark
        self.run_root = Path(run_root).expanduser().resolve()
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.agent_factory = agent_factory
        self.run_id = run_id
        self.model = model
        self.keep_failed_workspace = keep_failed_workspace
        self.keep_workspaces = keep_workspaces
        self.workspace_manager = WorkspaceManager(benchmark, self.run_root)
        self.validator = validator or ExternalValidator(benchmark.root)

    def _task_output(self, task: EvalTask) -> Path:
        path = self.run_root / "tasks" / task.id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def run(self, task: EvalTask) -> TaskRunResult:
        output = self._task_output(task)
        trace_path = output / "trace.jsonl"
        result_path = output / "result.json"
        recorder = TrajectoryRecorder()
        prepared: Optional[PreparedWorkspace] = None
        validator_result = ValidatorResult()
        final_answer = ""
        error = None
        status = "agent_error"
        started_at = utc_now_iso()
        started = time.perf_counter()

        try:
            prepared = self.workspace_manager.prepare(task)
            session_manager = SessionManager(storage_dir=str(output / "sessions"))
            agent = self.agent_factory(session_manager)
            if hasattr(agent, "set_permission_mode"):
                agent.set_permission_mode("auto")
            with _active_tool_workspace(prepared.path):
                try:
                    if hasattr(agent, "run_task"):
                        final_answer = agent.run_task(
                            task, prepared.path, output, recorder
                        )
                    else:
                        final_answer = agent.run(
                            task.prompt,
                            max_iterations=task.max_iterations
                            or self.benchmark.manifest.default_max_iterations,
                            on_event=recorder,
                        )
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    if (
                        not recorder.events
                        or recorder.events[-1].event_type != "agent_error"
                    ):
                        recorder.record(
                            "agent_error", error=error, metadata={"stage": "runner"}
                        )
                    status = (
                        "timeout"
                        if isinstance(exc, AgentDeadlineExceeded)
                        else "agent_error"
                    )
                    if status == "timeout":
                        recorder.record(
                            "agent_error",
                            error=error,
                            metadata={"stage": "agent", "status": "timeout"},
                        )
                else:
                    recorder.record(
                        "validator_start",
                        metadata={"command": list(task.validator.command)},
                    )
                    try:
                        validator_result = self.validator.run(task, prepared.path)
                    except Exception as exc:
                        error = f"{type(exc).__name__}: {exc}"
                        status = "validator_error"
                        recorder.record(
                            "validator_result",
                            error=error,
                            metadata={"status": status},
                        )
                    else:
                        if validator_result.timed_out:
                            status = "timeout"
                        elif validator_result.exit_code == 0:
                            status = "passed"
                        else:
                            status = "failed"
                        recorder.record(
                            "validator_result",
                            result=validator_result.stdout,
                            duration_ms=validator_result.duration_ms,
                            metadata={
                                "status": status,
                                "exit_code": validator_result.exit_code,
                                "timed_out": validator_result.timed_out,
                                "stderr": validator_result.stderr,
                            },
                        )
        except KeyboardInterrupt:
            status = "cancelled"
            error = "运行被用户中断"
            recorder.record("agent_error", error=error, metadata={"stage": "cancelled"})
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            status = "agent_error"
            recorder.record("agent_error", error=error, metadata={"stage": "setup"})
        finally:
            finished_at = utc_now_iso()
            duration_ms = int((time.perf_counter() - started) * 1000)
            if prepared is not None and (
                self.keep_workspaces
                or (self.keep_failed_workspace and status != "passed")
            ):
                prepared.keep = True

        try:
            recorder.write(trace_path)
            safety = SafetyMetrics(
                workspace_violations=sum(
                    1 for _ in recorder.results_containing("写入被沙箱拒绝")
                ),
                dangerous_command_rejections=sum(
                    1 for _ in recorder.results_containing("危险命令")
                ),
                user_confirmation_requests=0,
            )
            result = TaskRunResult(
                run_id=self.run_id,
                task_id=task.id,
                benchmark=self.benchmark.identity,
                model=self.model,
                status=status,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
                agent_iterations=recorder.max_iteration,
                tool_calls=recorder.tool_call_count,
                final_answer=final_answer,
                validator=validator_result,
                usage=UsageMetrics(),
                safety=safety,
                trace_file=str(trace_path.relative_to(self.run_root)),
                workspace_diff_file=None,
                error=error,
            )
            write_json_atomic(result_path, result.to_dict())
            return result
        finally:
            if prepared is not None:
                prepared.cleanup()
