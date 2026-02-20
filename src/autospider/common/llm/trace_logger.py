"""LLM 输入输出追踪日志（JSON 数组）。"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import config
from ..logger import get_logger

logger = get_logger(__name__)
_TRACE_WRITE_LOCK = threading.Lock()


def append_llm_trace(component: str, payload: dict[str, Any]) -> None:
    """追加一条 LLM 追踪记录到 JSON 文件。"""
    if not config.llm.trace_enabled:
        return

    max_chars = max(2000, int(config.llm.trace_max_chars))
    record = {
        "timestamp": datetime.now().isoformat(),
        "component": component,
        **_sanitize(payload, max_chars),
    }

    trace_path = Path(config.llm.trace_file)
    if not trace_path.is_absolute():
        trace_path = Path.cwd() / trace_path

    try:
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        with _TRACE_WRITE_LOCK:
            records = _load_trace_records(trace_path)
            records.append(record)
            text = json.dumps(records, ensure_ascii=False, indent=2, default=str) + "\n"
            trace_path.write_text(text, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[LLMTrace] 写入失败（忽略）: {exc}")


def _load_trace_records(path: Path) -> list[dict[str, Any]]:
    """读取既有追踪记录，兼容 JSON 数组与历史 JSONL。"""
    if not path.exists():
        return []

    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return _parse_jsonl_records(raw)

    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        records = parsed.get("records")
        if isinstance(records, list):
            return [item for item in records if isinstance(item, dict)]
    return []


def _parse_jsonl_records(raw: str) -> list[dict[str, Any]]:
    """解析历史 JSONL 文本。"""
    records: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def _sanitize(value: Any, max_chars: int) -> Any:
    """递归清洗/截断，防止日志爆量。"""
    if value is None:
        return None

    if isinstance(value, str):
        if len(value) <= max_chars:
            return value
        return value[:max_chars] + f"...[truncated {len(value) - max_chars} chars]"

    if isinstance(value, dict):
        return {str(k): _sanitize(v, max_chars) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        return [_sanitize(v, max_chars) for v in value]

    return value
