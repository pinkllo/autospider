from __future__ import annotations

from autospider.platform.config.settings import LoggingSettings
from autospider.platform.observability.logging import configure_logging, get_logger
from autospider.platform.shared_kernel.trace import clear_run_context, set_run_context


def test_structured_logging_includes_run_and_trace_context() -> None:
    captured: list[dict] = []

    def sink(message) -> None:
        captured.append(message.record)

    logger = configure_logging(
        LoggingSettings(log_level="INFO", log_json=False, log_event_prefix="autospider"),
        sink=sink,
    )
    clear_run_context()
    set_run_context(run_id="run-200", trace_id="trace-200")

    logger.bind(event="collection.subtask.started", context="collection", layer="application").info(
        "starting subtask run"
    )

    clear_run_context()

    assert captured[0]["extra"]["run_id"] == "run-200"
    assert captured[0]["extra"]["trace_id"] == "trace-200"
    assert captured[0]["extra"]["event"] == "collection.subtask.started"
    assert captured[0]["extra"]["context"] == "collection"
    assert captured[0]["extra"]["layer"] == "application"


def test_get_logger_uses_current_configured_logger_with_default_event() -> None:
    captured: list[dict] = []

    def sink(message) -> None:
        captured.append(message.record)

    configure_logging(
        LoggingSettings(log_level="INFO", log_json=False, log_event_prefix="autospider"),
        sink=sink,
    )
    clear_run_context()
    set_run_context(run_id="run-201", trace_id="trace-201")

    get_logger("autospider.platform.test", context="platform", layer="application").info("hello")

    clear_run_context()

    assert captured[0]["extra"]["run_id"] == "run-201"
    assert captured[0]["extra"]["trace_id"] == "trace-201"
    assert captured[0]["extra"]["event"] == "autospider.platform.log"
    assert captured[0]["extra"]["module"] == "autospider.platform.test"
