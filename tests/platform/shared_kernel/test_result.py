from __future__ import annotations

from pathlib import Path

from autospider.platform.shared_kernel.result import ErrorInfo, ResultEnvelope


def test_result_envelope_success_keeps_data_and_metrics() -> None:
    envelope = ResultEnvelope[dict[str, str]].success(
        data={"value": "ok"},
        trace_id="trace-001",
        run_id="run-001",
        metrics={"duration_ms": 12.0},
        artifacts_path=Path("output/runs/run-001"),
    )

    assert envelope.status == "success"
    assert envelope.data == {"value": "ok"}
    assert envelope.metrics == {"duration_ms": 12.0}
    assert envelope.artifacts_path == Path("output/runs/run-001")
    assert envelope.errors == []


def test_result_envelope_partial_keeps_errors() -> None:
    error = ErrorInfo(kind="validation", code="collection.partial", message="partial result")

    envelope = ResultEnvelope[list[str]].partial(
        data=["item-1"],
        trace_id="trace-002",
        errors=[error],
        metrics={"success_rate": 0.5},
    )

    assert envelope.status == "partial"
    assert envelope.data == ["item-1"]
    assert envelope.errors == [error]
    assert envelope.model_dump(mode="python")["trace_id"] == "trace-002"


def test_result_envelope_failed_clears_data() -> None:
    error = ErrorInfo(
        kind="infra",
        code="platform.timeout",
        message="timeout",
        context={"resource": "redis"},
    )

    envelope = ResultEnvelope[dict[str, str]].failed(trace_id="trace-003", errors=[error])

    assert envelope.status == "failed"
    assert envelope.data is None
    assert envelope.errors[0].context == {"resource": "redis"}
