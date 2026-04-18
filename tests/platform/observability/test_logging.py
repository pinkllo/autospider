from __future__ import annotations

from autospider.platform.config.settings import LoggingSettings
from autospider.platform.observability.logging import configure_logging
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
