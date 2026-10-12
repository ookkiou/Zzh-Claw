"""评测产物的原子写入工具。"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping


def _write_text_atomic(path: str | Path, content: str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise
    return target


def write_json_atomic(path: str | Path, data: Mapping[str, Any]) -> Path:
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    return _write_text_atomic(path, content)


def write_jsonl_atomic(path: str | Path, rows: Iterable[Mapping[str, Any]]) -> Path:
    content = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in rows
    )
    return _write_text_atomic(path, content)
