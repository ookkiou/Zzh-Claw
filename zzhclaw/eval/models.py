"""ZzhClaw-Eval 的稳定、可 JSON 序列化的数据模型。"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

TASK_SPLITS = frozenset({"train", "dev", "test"})
TASK_DIFFICULTIES = frozenset({"easy", "medium", "hard"})
TRACE_EVENT_TYPES = frozenset(
    {
        "agent_start",
        "tool_call",
        "tool_result",
        "agent_final",
        "agent_error",
        "validator_start",
        "validator_result",
    }
)
RUN_STATUSES = frozenset(
    {
        "passed",
        "failed",
        "agent_error",
        "validator_error",
        "timeout",
        "cancelled",
        "invalid_task",
    }
)
TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def utc_now_iso() -> str:
    """返回带时区、可排序的 ISO 时间。"""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} 必须是 JSON object")
    return value


def _required_string(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} 必须是非空字符串")
    return value.strip()


def _optional_string(data: Mapping[str, Any], key: str) -> Optional[str]:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} 必须是字符串或 null")
    return value


def _positive_int(value: Any, name: str, *, optional: bool = False) -> Optional[int]:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} 必须是正整数")
    return value


def _non_negative_int(
    value: Any, name: str, *, optional: bool = False
) -> Optional[int]:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} 必须是非负整数")
    return value


def _json_ready(value: Any) -> Any:
    """把 dataclass/asdict 中的 tuple 递归转成 JSON 惯用的 list。"""
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    return value


class JsonModel:
    """为所有模型提供一致的字典导出。"""

    def to_dict(self) -> Dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class ValidatorConfig(JsonModel):
    command: Tuple[str, ...]
    timeout_seconds: int = 60
    env: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.command or any(
            not isinstance(part, str) or not part for part in self.command
        ):
            raise ValueError("validator.command 必须是非空字符串数组")
        _positive_int(self.timeout_seconds, "validator.timeout_seconds")
        if any(
            not isinstance(k, str) or not isinstance(v, str)
            for k, v in self.env.items()
        ):
            raise ValueError("validator.env 的 key 和 value 必须都是字符串")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ValidatorConfig":
        data = _mapping(raw, "validator")
        command = data.get("command")
        if not isinstance(command, Sequence) or isinstance(command, (str, bytes)):
            raise ValueError("validator.command 必须是字符串数组")
        env = data.get("env", {})
        env = dict(_mapping(env, "validator.env"))
        return cls(
            command=tuple(command),
            timeout_seconds=_positive_int(
                data.get("timeout_seconds", 60), "validator.timeout_seconds"
            ),
            env=env,
        )


@dataclass(frozen=True)
class BenchmarkManifest(JsonModel):
    name: str
    version: str
    description: str
    task_file: str
    created_at: str
    default_timeout_seconds: int = 180
    default_max_iterations: int = 12

    def __post_init__(self) -> None:
        for key in ("name", "version", "task_file", "created_at"):
            value = getattr(self, key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"manifest.{key} 必须是非空字符串")
        if not isinstance(self.description, str):
            raise ValueError("manifest.description 必须是字符串")
        _positive_int(self.default_timeout_seconds, "manifest.default_timeout_seconds")
        _positive_int(self.default_max_iterations, "manifest.default_max_iterations")

    @property
    def identity(self) -> str:
        return f"{self.name}@{self.version}"

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "BenchmarkManifest":
        data = _mapping(raw, "manifest")
        return cls(
            name=_required_string(data, "name"),
            version=_required_string(data, "version"),
            description=data.get("description", ""),
            task_file=_required_string(data, "task_file"),
            created_at=_required_string(data, "created_at"),
            default_timeout_seconds=_positive_int(
                data.get("default_timeout_seconds", 180),
                "manifest.default_timeout_seconds",
            ),
            default_max_iterations=_positive_int(
                data.get("default_max_iterations", 12),
                "manifest.default_max_iterations",
            ),
        )


@dataclass(frozen=True)
class EvalTask(JsonModel):
    id: str
    title: str
    prompt: str
    workspace: str
    validator: ValidatorConfig
    max_iterations: Optional[int] = None
    task_timeout_seconds: Optional[int] = None
    tags: Tuple[str, ...] = field(default_factory=tuple)
    split: str = "test"
    difficulty: Optional[str] = None

    def __post_init__(self) -> None:
        for key in ("id", "title", "prompt", "workspace"):
            value = getattr(self, key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"task.{key} 必须是非空字符串")
        if not TASK_ID_PATTERN.fullmatch(self.id):
            raise ValueError(
                "task.id 只能包含字母、数字、点、下划线和连字符，且最长 128 字符"
            )
        _positive_int(self.max_iterations, "task.max_iterations", optional=True)
        _positive_int(
            self.task_timeout_seconds, "task.task_timeout_seconds", optional=True
        )
        if not isinstance(self.split, str) or self.split not in TASK_SPLITS:
            raise ValueError(f"task.split 必须是 {sorted(TASK_SPLITS)} 之一")
        if self.difficulty is not None and (
            not isinstance(self.difficulty, str)
            or self.difficulty not in TASK_DIFFICULTIES
        ):
            raise ValueError(f"task.difficulty 必须是 {sorted(TASK_DIFFICULTIES)} 之一")
        if any(not isinstance(tag, str) or not tag.strip() for tag in self.tags):
            raise ValueError("task.tags 必须是非空字符串数组")
        if len(set(self.tags)) != len(self.tags):
            raise ValueError("task.tags 不能包含重复项")

    def with_defaults(self, manifest: BenchmarkManifest) -> "EvalTask":
        return EvalTask(
            id=self.id,
            title=self.title,
            prompt=self.prompt,
            workspace=self.workspace,
            validator=self.validator,
            max_iterations=self.max_iterations or manifest.default_max_iterations,
            task_timeout_seconds=self.task_timeout_seconds
            or manifest.default_timeout_seconds,
            tags=self.tags,
            split=self.split,
            difficulty=self.difficulty,
        )

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "EvalTask":
        data = _mapping(raw, "task")
        tags = data.get("tags", [])
        if not isinstance(tags, Sequence) or isinstance(tags, (str, bytes)):
            raise ValueError("task.tags 必须是字符串数组")
        return cls(
            id=_required_string(data, "id"),
            title=_required_string(data, "title"),
            prompt=_required_string(data, "prompt"),
            workspace=_required_string(data, "workspace"),
            validator=ValidatorConfig.from_dict(data.get("validator")),
            max_iterations=_positive_int(
                data.get("max_iterations"), "task.max_iterations", optional=True
            ),
            task_timeout_seconds=_positive_int(
                data.get("task_timeout_seconds"),
                "task.task_timeout_seconds",
                optional=True,
            ),
            tags=tuple(tags),
            split=data.get("split", "test"),
            difficulty=_optional_string(data, "difficulty"),
        )


@dataclass(frozen=True)
class TraceEvent(JsonModel):
    sequence: int
    event_type: str
    timestamp: str = field(default_factory=utc_now_iso)
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    arguments: Optional[Dict[str, Any]] = None
    result: Optional[str] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _non_negative_int(self.sequence, "trace.sequence")
        if (
            not isinstance(self.event_type, str)
            or self.event_type not in TRACE_EVENT_TYPES
        ):
            raise ValueError(
                f"trace.event_type 必须是 {sorted(TRACE_EVENT_TYPES)} 之一"
            )
        if not isinstance(self.timestamp, str) or not self.timestamp:
            raise ValueError("trace.timestamp 必须是非空字符串")
        _non_negative_int(self.duration_ms, "trace.duration_ms", optional=True)
        if self.arguments is not None and not isinstance(self.arguments, dict):
            raise ValueError("trace.arguments 必须是 object 或 null")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "TraceEvent":
        data = _mapping(raw, "trace")
        arguments = data.get("arguments")
        metadata = data.get("metadata", {})
        if arguments is not None:
            arguments = dict(_mapping(arguments, "trace.arguments"))
        return cls(
            sequence=_non_negative_int(data.get("sequence"), "trace.sequence"),
            event_type=_required_string(data, "event_type"),
            timestamp=data.get("timestamp") or utc_now_iso(),
            tool_call_id=_optional_string(data, "tool_call_id"),
            tool_name=_optional_string(data, "tool_name"),
            arguments=arguments,
            result=_optional_string(data, "result"),
            duration_ms=_non_negative_int(
                data.get("duration_ms"), "trace.duration_ms", optional=True
            ),
            error=_optional_string(data, "error"),
            metadata=dict(_mapping(metadata, "trace.metadata")),
        )


@dataclass(frozen=True)
class ValidatorResult(JsonModel):
    exit_code: Optional[int] = None
    timed_out: bool = False
    stdout: str = ""
    stderr: str = ""
    duration_ms: Optional[int] = None

    def __post_init__(self) -> None:
        if self.exit_code is not None and (
            isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int)
        ):
            raise ValueError("validator_result.exit_code 必须是整数或 null")
        if not isinstance(self.timed_out, bool):
            raise ValueError("validator_result.timed_out 必须是 boolean")
        if not isinstance(self.stdout, str) or not isinstance(self.stderr, str):
            raise ValueError("validator_result.stdout/stderr 必须是字符串")
        _non_negative_int(
            self.duration_ms, "validator_result.duration_ms", optional=True
        )

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ValidatorResult":
        data = _mapping(raw, "validator_result")
        return cls(
            exit_code=data.get("exit_code"),
            timed_out=data.get("timed_out", False),
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            duration_ms=_non_negative_int(
                data.get("duration_ms"), "validator_result.duration_ms", optional=True
            ),
        )


@dataclass(frozen=True)
class UsageMetrics(JsonModel):
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    estimated_cost: Optional[float] = None
    currency: Optional[str] = None

    def __post_init__(self) -> None:
        _non_negative_int(self.input_tokens, "usage.input_tokens", optional=True)
        _non_negative_int(self.output_tokens, "usage.output_tokens", optional=True)
        if self.estimated_cost is not None:
            if isinstance(self.estimated_cost, bool) or not isinstance(
                self.estimated_cost, (int, float)
            ):
                raise ValueError("usage.estimated_cost 必须是数字或 null")
            if self.estimated_cost < 0:
                raise ValueError("usage.estimated_cost 不能为负数")
        if self.currency is not None and not isinstance(self.currency, str):
            raise ValueError("usage.currency 必须是字符串或 null")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "UsageMetrics":
        data = _mapping(raw, "usage")
        return cls(
            input_tokens=_non_negative_int(
                data.get("input_tokens"), "usage.input_tokens", optional=True
            ),
            output_tokens=_non_negative_int(
                data.get("output_tokens"), "usage.output_tokens", optional=True
            ),
            estimated_cost=data.get("estimated_cost"),
            currency=_optional_string(data, "currency"),
        )


@dataclass(frozen=True)
class SafetyMetrics(JsonModel):
    workspace_violations: int = 0
    dangerous_command_rejections: int = 0
    user_confirmation_requests: int = 0

    def __post_init__(self) -> None:
        _non_negative_int(self.workspace_violations, "safety.workspace_violations")
        _non_negative_int(
            self.dangerous_command_rejections,
            "safety.dangerous_command_rejections",
        )
        _non_negative_int(
            self.user_confirmation_requests,
            "safety.user_confirmation_requests",
        )

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SafetyMetrics":
        data = _mapping(raw, "safety")
        return cls(
            workspace_violations=_non_negative_int(
                data.get("workspace_violations", 0), "safety.workspace_violations"
            ),
            dangerous_command_rejections=_non_negative_int(
                data.get("dangerous_command_rejections", 0),
                "safety.dangerous_command_rejections",
            ),
            user_confirmation_requests=_non_negative_int(
                data.get("user_confirmation_requests", 0),
                "safety.user_confirmation_requests",
            ),
        )


@dataclass(frozen=True)
class TaskRunResult(JsonModel):
    run_id: str
    task_id: str
    benchmark: str
    model: str
    status: str
    started_at: str
    finished_at: str
    duration_ms: int
    agent_iterations: int = 0
    tool_calls: int = 0
    final_answer: str = ""
    validator: ValidatorResult = field(default_factory=ValidatorResult)
    usage: UsageMetrics = field(default_factory=UsageMetrics)
    safety: SafetyMetrics = field(default_factory=SafetyMetrics)
    trace_file: Optional[str] = None
    workspace_diff_file: Optional[str] = None
    error: Optional[str] = None

    def __post_init__(self) -> None:
        for key in (
            "run_id",
            "task_id",
            "benchmark",
            "model",
            "started_at",
            "finished_at",
        ):
            value = getattr(self, key)
            if not isinstance(value, str) or not value:
                raise ValueError(f"result.{key} 必须是非空字符串")
        if not isinstance(self.status, str) or self.status not in RUN_STATUSES:
            raise ValueError(f"result.status 必须是 {sorted(RUN_STATUSES)} 之一")
        _non_negative_int(self.duration_ms, "result.duration_ms")
        _non_negative_int(self.agent_iterations, "result.agent_iterations")
        _non_negative_int(self.tool_calls, "result.tool_calls")
        if not isinstance(self.final_answer, str):
            raise ValueError("result.final_answer 必须是字符串")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "TaskRunResult":
        data = _mapping(raw, "result")
        return cls(
            run_id=_required_string(data, "run_id"),
            task_id=_required_string(data, "task_id"),
            benchmark=_required_string(data, "benchmark"),
            model=_required_string(data, "model"),
            status=_required_string(data, "status"),
            started_at=_required_string(data, "started_at"),
            finished_at=_required_string(data, "finished_at"),
            duration_ms=_non_negative_int(
                data.get("duration_ms"), "result.duration_ms"
            ),
            agent_iterations=_non_negative_int(
                data.get("agent_iterations", 0), "result.agent_iterations"
            ),
            tool_calls=_non_negative_int(
                data.get("tool_calls", 0), "result.tool_calls"
            ),
            final_answer=data.get("final_answer", ""),
            validator=ValidatorResult.from_dict(data.get("validator", {})),
            usage=UsageMetrics.from_dict(data.get("usage", {})),
            safety=SafetyMetrics.from_dict(data.get("safety", {})),
            trace_file=_optional_string(data, "trace_file"),
            workspace_diff_file=_optional_string(data, "workspace_diff_file"),
            error=_optional_string(data, "error"),
        )
