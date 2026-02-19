"""LLM 输入输出追踪日志（JSONL）。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import config
from ..logger import get_logger

logger = get_logger(__name__)


def append_llm_trace(component: str, payload: dict[str, Any]) -> None:
    """追加一条 LLM 追踪记录到 JSONL 文件。"""
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
        with open(trace_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[LLMTrace] 写入失败（忽略）: {exc}")


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
