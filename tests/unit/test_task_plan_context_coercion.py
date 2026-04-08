from __future__ import annotations

from autospider.domain.planning import TaskPlan


def test_task_plan_model_validate_coerces_boolean_context_values_to_strings():
    plan = TaskPlan.model_validate(
        {
            "plan_id": "plan_1",
            "original_request": "采集公告",
            "site_url": "https://example.com",
            "subtasks": [
                {
                    "id": "leaf_001",
                    "name": "工程建设",
                    "list_url": "https://example.com/list",
                    "task_description": "采集工程建设",
                    "context": {
                        "reliable_for_aggregation": True,
                        "durably_persisted": False,
                    },
                }
            ],
            "nodes": [
                {
                    "node_id": "node_1",
                    "name": "工程建设",
                    "node_type": "leaf",
                    "context": {
                        "enabled": True,
                    },
                }
            ],
            "journal": [
                {
                    "entry_id": "journal_1",
                    "metadata": {
                        "flag": True,
                    },
                }
            ],
        }
    )

    assert plan.subtasks[0].context["reliable_for_aggregation"] == "true"
    assert plan.subtasks[0].context["durably_persisted"] == "false"
    assert plan.nodes[0].context["enabled"] == "true"
    assert plan.journal[0].metadata["flag"] == "true"
