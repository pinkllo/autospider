from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

from loguru import logger

from autospider.platform.config.settings import LoggingSettings
from autospider.platform.observability.log_schema import (
    DEFAULT_CONTEXT,
    DEFAULT_EVENT,
    DEFAULT_LAYER,
)
from autospider.platform.shared_kernel.trace import get_run_id, get_trace_id

RecordPatcher = Callable[[dict[str, Any]], None]


def configure_logging(
    settings: LoggingSettings | None = None,
    *,
    sink: Any | None = None,
) -> Any:
    effective_settings = settings or LoggingSettings()
    patched_logger = logger.patch(_build_record_patcher(effective_settings))
    patched_logger.remove()
    patched_logger.add(
        sink or sys.stderr,
        level=effective_settings.log_level,
        serialize=effective_settings.log_json,
        backtrace=False,
        diagnose=False,
    )
    return patched_logger


def get_logger(name: str, *, context: str = DEFAULT_CONTEXT, layer: str = DEFAULT_LAYER) -> Any:
    return logger.bind(module=name, context=context, layer=layer)


def _build_record_patcher(settings: LoggingSettings) -> RecordPatcher:
    def _patch(record: dict[str, Any]) -> None:
        extra = record["extra"]
        extra.setdefault("event", f"{settings.log_event_prefix}.{DEFAULT_EVENT}")
        extra.setdefault("layer", DEFAULT_LAYER)
        extra.setdefault("context", DEFAULT_CONTEXT)
        extra["run_id"] = get_run_id()
        extra["trace_id"] = get_trace_id()

    return _patch
