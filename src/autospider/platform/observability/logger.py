"""统一日志系统。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.logging import RichHandler

from autospider.platform.config.runtime import get_config
from autospider.platform.observability.log_schema import (
    DEFAULT_CONTEXT,
    DEFAULT_EVENT,
    DEFAULT_LAYER,
    event_name,
)
from autospider.platform.shared_kernel.trace import get_run_id, get_trace_id
from autospider.platform.shared_kernel.utils.paths import resolve_output_path, resolve_repo_path

console = Console()
_BOOTSTRAPPED = False
_CURRENT_LOG_FILE = ""
_CURRENT_SHOW_LOCALS = False
_EVENT_PREFIX = "autospider"
_CONSOLE_HANDLER: logging.Handler | None = None
_FILE_HANDLER: logging.Handler | None = None

LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


class StructuredLoggerAdapter(logging.LoggerAdapter):
    def bind(self, **context: Any) -> "StructuredLoggerAdapter":
        payload = dict(self.extra)
        payload.update({key: value for key, value in context.items() if value is not None})
        return StructuredLoggerAdapter(self.logger, payload)

    def process(self, msg: object, kwargs: dict[str, Any]) -> tuple[object, dict[str, Any]]:
        payload = dict(self.extra)
        payload.update(dict(kwargs.pop("extra", {}) or {}))
        payload.setdefault("context", DEFAULT_CONTEXT)
        payload.setdefault("layer", DEFAULT_LAYER)
        payload.setdefault("event", _default_event_name())
        payload["run_id"] = get_run_id()
        payload["trace_id"] = get_trace_id()
        kwargs["extra"] = payload
        return msg, kwargs

    def __getattr__(self, name: str) -> Any:
        return getattr(self.logger, name)


def _logging_config(*, reload: bool = False):
    return get_config(reload=reload).logging


def _resolve_log_level(level_name: str) -> int:
    return LOG_LEVEL_MAP.get(str(level_name or "").strip().upper(), logging.INFO)


def _default_event_name() -> str:
    return event_name(_EVENT_PREFIX, DEFAULT_EVENT)


def get_log_level() -> int:
    return _resolve_log_level(_logging_config().log_level)


def _resolve_runtime_log_file(output_dir: str | None = None) -> Path:
    if output_dir:
        return resolve_output_path(output_dir, "runtime.log")
    configured = str(_logging_config().log_file or "").strip() or "output/runtime.log"
    return resolve_repo_path(configured)


def _build_console_handler(level: int, *, show_locals: bool) -> logging.Handler:
    handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        rich_tracebacks=True,
        tracebacks_show_locals=show_locals,
        markup=False,
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(message)s", datefmt="[%X]"))
    return handler


def _build_file_handler(log_file: Path, level: int) -> logging.Handler:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    return handler


def _configure_root_logger(level: int, log_file: Path, *, show_locals: bool) -> None:
    global _CONSOLE_HANDLER, _FILE_HANDLER, _CURRENT_LOG_FILE, _CURRENT_SHOW_LOCALS

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if _CONSOLE_HANDLER is not None and _CURRENT_SHOW_LOCALS != show_locals:
        root_logger.removeHandler(_CONSOLE_HANDLER)
        _CONSOLE_HANDLER.close()
        _CONSOLE_HANDLER = None

    if _CONSOLE_HANDLER is None:
        _CONSOLE_HANDLER = _build_console_handler(level, show_locals=show_locals)
        _CURRENT_SHOW_LOCALS = show_locals
    else:
        _CONSOLE_HANDLER.setLevel(level)
    root_logger.addHandler(_CONSOLE_HANDLER)

    target_log_file = str(log_file)
    if _FILE_HANDLER is not None and _CURRENT_LOG_FILE != target_log_file:
        root_logger.removeHandler(_FILE_HANDLER)
        _FILE_HANDLER.close()
        _FILE_HANDLER = None

    if _FILE_HANDLER is None:
        _FILE_HANDLER = _build_file_handler(log_file, level)
        _CURRENT_LOG_FILE = target_log_file
    else:
        _FILE_HANDLER.setLevel(level)
    root_logger.addHandler(_FILE_HANDLER)


def bootstrap_logging(*, output_dir: str | None = None) -> None:
    global _BOOTSTRAPPED, _EVENT_PREFIX

    logging_config = _logging_config(reload=True)
    _EVENT_PREFIX = str(logging_config.event_prefix or "").strip() or "autospider"
    level = _resolve_log_level(logging_config.log_level)
    log_file = _resolve_runtime_log_file(output_dir)
    _configure_root_logger(level, log_file, show_locals=bool(logging_config.show_locals))
    _BOOTSTRAPPED = True


def get_logger(
    name: str,
    *,
    context: str = DEFAULT_CONTEXT,
    layer: str = DEFAULT_LAYER,
) -> StructuredLoggerAdapter:
    if not _BOOTSTRAPPED:
        bootstrap_logging()
    logger = logging.getLogger(name)
    logger.setLevel(logging.NOTSET)
    logger.propagate = True
    return StructuredLoggerAdapter(
        logger,
        {
            "context": str(context or "").strip() or DEFAULT_CONTEXT,
            "layer": str(layer or "").strip() or DEFAULT_LAYER,
        },
    )


def setup_file_logging(
    logger: logging.Logger | StructuredLoggerAdapter,
    log_file: str,
    level: int = logging.DEBUG,
) -> None:
    target = logger.logger if isinstance(logger, StructuredLoggerAdapter) else logger
    target.addHandler(_build_file_handler(resolve_repo_path(log_file), level))


class LogContext:
    def __init__(self, logger: logging.Logger | StructuredLoggerAdapter, **context: Any):
        self.logger = logger
        self.context = context
        self._old_extra: dict[str, Any] = {}

    def __enter__(self):
        for key, value in self.context.items():
            self._old_extra[key] = getattr(self.logger, key, None)
            setattr(self.logger, key, value)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for key, old_value in self._old_extra.items():
            if old_value is None:
                delattr(self.logger, key)
            else:
                setattr(self.logger, key, old_value)
        return False


def get_crawler_logger() -> StructuredLoggerAdapter:
    return get_logger("autospider.crawler")


def get_llm_logger() -> StructuredLoggerAdapter:
    return get_logger("autospider.llm")


def get_browser_logger() -> StructuredLoggerAdapter:
    return get_logger("autospider.browser")
