from __future__ import annotations

from autospider.graph.nodes import shared_nodes


def test_finalize_result_prefers_explicit_outcome_state():
    result = shared_nodes.finalize_result(
        {
            "summary": {
                "outcome_state": "partial_success",
                "completed": 5,
                "failed": 0,
            }
        }
    )

    assert result["status"] == "partial_success"


def test_finalize_result_ignores_technical_ok_status_and_preserves_no_data():
    result = shared_nodes.finalize_result(
        {
            "result": {"status": "ok"},
            "summary": {
                "outcome_state": "no_data",
                "completed": 0,
                "failed": 0,
                "no_data": 3,
            },
        }
    )

    assert result["status"] == "no_data"


def test_finalize_result_inferrs_no_data_from_dispatch_summary():
    result = shared_nodes.finalize_result(
        {
            "summary": {
                "completed": 0,
                "failed": 0,
                "no_data": 2,
            }
        }
    )

    assert result["status"] == "no_data"


def test_build_summary_includes_runtime_metadata():
    result = shared_nodes.build_summary(
        {
            "thread_id": "thread-1",
            "request_id": "request-1",
            "entry_mode": "chat-pipeline",
            "summary": {
                "total_urls": 4,
                "success_count": 4,
                "promotion_state": "reusable",
                "execution_state": "completed",
                "execution_id": "exec_keep",
            },
        }
    )

    summary = result["summary"]
    assert summary["thread_id"] == "thread-1"
    assert summary["request_id"] == "request-1"
    assert summary["entry_mode"] == "chat-pipeline"
    assert summary["execution_id"] == "exec_keep"
