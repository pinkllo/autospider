"""LLM 输入输出追踪日志（JSONL append-only）。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import threading
from pathlib import Path
from typing import Any

from autospider.platform.config.runtime import config
from autospider.platform.observability.logger import get_logger
from autospider.platform.shared_kernel.trace import get_run_id, get_trace_id
from autospider.platform.shared_kernel.utils.paths import resolve_repo_path

logger = get_logger(__name__)
_TRACE_WRITE_LOCK = threading.Lock()
_DEFAULT_TRACE_FILE = "output/llm_trace.jsonl"


def append_llm_trace(component: str, payload: dict[str, Any]) -> None:
    """追加一条 LLM 追踪记录到 JSONL 文件。"""
    if not config.llm.trace_enabled:
        return

    max_chars = max(2000, int(config.llm.trace_max_chars))
    record = _build_trace_record(component, payload, max_chars)
    trace_path = _resolve_trace_path(config.llm.trace_file)

    try:
        _append_record(trace_path, record)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[LLMTrace] 写入失败: component=%s path=%s error=%s",
            component,
            trace_path,
            exc,
            exc_info=True,
        )


def _build_trace_record(component: str, payload: dict[str, Any], max_chars: int) -> dict[str, Any]:
    sanitized = _sanitize(payload, max_chars)
    input_payload = _normalize_trace_value(sanitized.pop("input", None))
    output_payload = _normalize_trace_value(sanitized.pop("output", None))
    response_summary = sanitized.pop("response_summary", None)
    if response_summary is None and isinstance(output_payload, dict):
        response_summary = output_payload.get("response_summary")

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "component": component,
        "run_id": get_run_id(),
        "trace_id": get_trace_id(),
        "model": sanitized.pop("model", None),
        "input": input_payload,
        "output": output_payload,
        "response_summary": _normalize_trace_value(response_summary),
        "error": _normalize_error(sanitized.pop("error", None)),
        **sanitized,
    }


def _resolve_trace_path(raw_path: str) -> Path:
    target = str(raw_path or "").strip() or _DEFAULT_TRACE_FILE
    return resolve_repo_path(target)


def _append_record(path: Path, record: dict[str, Any]) -> None:
    line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _TRACE_WRITE_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)


def _normalize_trace_value(value: Any) -> Any:
    if value is None:
        return {}
    return value


def _normalize_error(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        normalized = dict(value)
        if "type" not in normalized and "message" in normalized:
            normalized["type"] = "Error"
        return normalized
    if isinstance(value, BaseException):
        return {"type": type(value).__name__, "message": str(value)}
    return {"type": type(value).__name__, "message": str(value)}


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
