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
