from __future__ import annotations

import importlib
import logging

import pytest

from autospider.platform.shared_kernel.trace import clear_run_context, set_run_context


class _CaptureHandler(logging.Handler):
    def __init__(self, records: list[logging.LogRecord]) -> None:
        super().__init__()
        self._records = records

    def emit(self, record: logging.LogRecord) -> None:
        self._records.append(record)


def _detach_logger_handlers(logger_module) -> None:
    root_logger = logging.getLogger()
    for handler_name in ("_CONSOLE_HANDLER", "_FILE_HANDLER"):
        handler = getattr(logger_module, handler_name, None)
        if handler is None:
            continue
        root_logger.removeHandler(handler)
        handler.close()
        setattr(logger_module, handler_name, None)
    logger_module._CURRENT_LOG_FILE = ""
    logger_module._CURRENT_SHOW_LOCALS = False
    logger_module._BOOTSTRAPPED = False


@pytest.fixture()
def load_logger_module():
    def _load():
        import autospider.platform.observability.logger as logger_module

        _detach_logger_handlers(logger_module)
        return importlib.reload(logger_module)

    yield _load

    import autospider.platform.observability.logger as logger_module

    _detach_logger_handlers(logger_module)
    clear_run_context()


def test_structured_logging_includes_run_and_trace_context(load_logger_module) -> None:
    logger_module = load_logger_module()
    captured: list[logging.LogRecord] = []
    handler = _CaptureHandler(captured)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    try:
        logger_module.bootstrap_logging()
        clear_run_context()
        set_run_context(run_id="run-200", trace_id="trace-200")

        logger = logger_module.get_logger(
            "autospider.platform.test",
            context="collection",
            layer="application",
        ).bind(event="collection.subtask.started")
        logger.info("starting subtask run")
    finally:
        clear_run_context()
        root_logger.removeHandler(handler)

    assert captured[0].run_id == "run-200"
    assert captured[0].trace_id == "trace-200"
    assert captured[0].event == "collection.subtask.started"
    assert captured[0].context == "collection"
    assert captured[0].layer == "application"


def test_get_logger_uses_default_event_name(load_logger_module) -> None:
    logger_module = load_logger_module()
    captured: list[logging.LogRecord] = []
    handler = _CaptureHandler(captured)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    try:
        logger_module.bootstrap_logging()
        clear_run_context()
        set_run_context(run_id="run-201", trace_id="trace-201")

        logger_module.get_logger(
            "autospider.platform.test",
            context="platform",
            layer="application",
        ).info("hello")
    finally:
        clear_run_context()
        root_logger.removeHandler(handler)

    assert captured[0].run_id == "run-201"
    assert captured[0].trace_id == "trace-201"
    assert captured[0].event == "autospider.platform.log"
    assert captured[0].name == "autospider.platform.test"
