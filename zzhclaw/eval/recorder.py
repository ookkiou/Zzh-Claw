"""把 Agent 的结构化事件转换为稳定的 TraceEvent 轨迹。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from .models import TraceEvent
from .storage import write_jsonl_atomic

_EVENT_FIELDS = {
    "event_type",
    "tool_call_id",
    "tool_name",
    "arguments",
    "result",
    "duration_ms",
    "error",
    "metadata",
}


class TrajectoryRecorder:
    """可直接作为 ``Agent.run(on_event=...)`` 回调。"""

    def __init__(self) -> None:
        self._events: List[TraceEvent] = []

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        return tuple(self._events)

    @property
    def tool_call_count(self) -> int:
        return sum(event.event_type == "tool_call" for event in self._events)

    @property
    def max_iteration(self) -> int:
        values = []
        for event in self._events:
            value = event.metadata.get("iteration")
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                values.append(value)
        return max(values, default=0)

    def __call__(self, raw: Mapping[str, Any]) -> TraceEvent:
        if not isinstance(raw, Mapping):
            raise ValueError("Agent event 必须是 mapping")
        event_type = raw.get("event_type")
        metadata = raw.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise ValueError("Agent event metadata 必须是 mapping")
        merged_metadata: Dict[str, Any] = dict(metadata)
        for key, value in raw.items():
            if key not in _EVENT_FIELDS:
                merged_metadata[key] = value

        event = TraceEvent(
            sequence=len(self._events),
            event_type=event_type,
            tool_call_id=raw.get("tool_call_id"),
            tool_name=raw.get("tool_name"),
            arguments=raw.get("arguments"),
            result=raw.get("result"),
            duration_ms=raw.get("duration_ms"),
            error=raw.get("error"),
            metadata=merged_metadata,
        )
        self._events.append(event)
        return event

    def record(self, event_type: str, **payload: Any) -> TraceEvent:
        return self({"event_type": event_type, **payload})

    def write(self, path: str | Path) -> Path:
        return write_jsonl_atomic(path, (event.to_dict() for event in self._events))

    def results_containing(self, text: str) -> Iterable[TraceEvent]:
        return (
            event
            for event in self._events
            if event.event_type == "tool_result" and text in (event.result or "")
        )
