"""ZzhClaw-Eval 的任务加载、执行和批量评测公共接口。"""

from .batch import BatchRunner
from .evaluator import ExternalValidator, ValidatorExecutionError
from .models import (
    BenchmarkManifest,
    EvalTask,
    SafetyMetrics,
    TaskRunResult,
    TraceEvent,
    UsageMetrics,
    ValidatorConfig,
    ValidatorResult,
)
from .recorder import TrajectoryRecorder
from .runner import TaskRunner
from .task_loader import BenchmarkLoadError, LoadedBenchmark, load_benchmark
from .workspace import PreparedWorkspace, WorkspaceError, WorkspaceManager

__all__ = [
    "BatchRunner",
    "BenchmarkLoadError",
    "BenchmarkManifest",
    "EvalTask",
    "ExternalValidator",
    "LoadedBenchmark",
    "PreparedWorkspace",
    "SafetyMetrics",
    "TaskRunResult",
    "TaskRunner",
    "TraceEvent",
    "TrajectoryRecorder",
    "UsageMetrics",
    "ValidatorConfig",
    "ValidatorResult",
    "ValidatorExecutionError",
    "WorkspaceError",
    "WorkspaceManager",
    "load_benchmark",
]
