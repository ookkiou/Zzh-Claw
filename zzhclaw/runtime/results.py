"""保持文本工具 API 兼容，同时给轨迹提供结构化结果。"""

from __future__ import annotations


class ToolResult(str):
    def __new__(cls, text, *, error_code=None, metadata=None):
        result = super().__new__(cls, text)
        result.error_code = error_code
        result.metadata = dict(metadata or {})
        return result

    def trace_metadata(self):
        return {
            **self.metadata,
            "error_code": self.error_code,
            "result_schema_version": 1,
        }
