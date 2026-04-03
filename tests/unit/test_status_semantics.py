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


def test_build_summary_registers_only_reusable_tasks(monkeypatch, tmp_path):
    calls: list[dict] = []

    class _FakeRegistry:
        def __init__(self, registry_path: str):
            self.registry_path = registry_path

        def register(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(shared_nodes, "TaskRegistry", _FakeRegistry)

    shared_nodes.build_summary(
        {
            "node_status": "ok",
            "normalized_params": {
                "list_url": "https://example.com/list",
                "task_description": "采集公告",
                "output_dir": str(tmp_path),
                "fields": [{"name": "title"}],
            },
            "summary": {
                "total_urls": 4,
                "success_count": 3,
                "promotion_state": "diagnostic_only",
                "execution_state": "completed",
                "execution_id": "exec_skip",
            },
        }
    )
    assert calls == []

    shared_nodes.build_summary(
        {
            "node_status": "ok",
            "normalized_params": {
                "list_url": "https://example.com/list",
                "task_description": "采集公告",
                "output_dir": str(tmp_path),
                "fields": [{"name": "title"}],
            },
            "summary": {
                "total_urls": 4,
                "success_count": 4,
                "promotion_state": "reusable",
                "execution_state": "completed",
                "execution_id": "exec_keep",
            },
        }
    )

    assert len(calls) == 1
    assert calls[0]["status"] == "completed"
    assert calls[0]["execution_id"] == "exec_keep"
