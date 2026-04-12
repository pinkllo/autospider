from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.graph.nodes.entry_nodes import (
    chat_prepare_execution_handoff,
    normalize_pipeline_params,
)


def test_normalize_pipeline_params_exposes_empty_runtime_payload_slots() -> None:
    state = {
        "cli_args": {
            "list_url": "https://example.com/notices",
            "task_description": "采集公告",
            "output_dir": "output",
        }
    }

    result = normalize_pipeline_params(state)
    normalized = result["normalized_params"]

    assert "decision_context" in normalized
    assert "world_snapshot" in normalized
    assert "control_snapshot" in normalized
    assert "failure_records" in normalized
    assert normalized["decision_context"] == {}
    assert normalized["world_snapshot"] == {}
    assert normalized["control_snapshot"] == {}
    assert normalized["failure_records"] == []


def test_chat_prepare_execution_handoff_exposes_empty_runtime_payload_slots() -> None:
    state = {
        "cli_args": {
            "output_dir": "output",
            "request": "采集公告",
        },
        "conversation": {
            "clarified_task": {
                "list_url": "https://example.com/notices",
                "task_description": "采集公告",
                "fields": [{"name": "title", "description": "公告标题", "required": True}],
                "max_pages": 3,
                "target_url_count": 8,
                "consumer_concurrency": 2,
                "field_explore_count": 1,
                "field_validate_count": 1,
            },
            "selected_skills": [],
        },
    }

    result = chat_prepare_execution_handoff(state)
    normalized = result["normalized_params"]

    assert normalized["decision_context"] == {}
    assert normalized["world_snapshot"] == {}
    assert normalized["control_snapshot"] == {}
    assert normalized["failure_records"] == []
