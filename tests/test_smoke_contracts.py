from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.platform.llm.contracts import validate_task_clarifier_payload


def test_validate_task_clarifier_payload_accepts_grouping_semantics() -> None:
    payload, errors = validate_task_clarifier_payload(
        {
            "status": "ready",
            "intent": "collect",
            "task_description": "按学科分类采集专业列表",
            "list_url": "https://example.com/majors",
            "fields": [
                {
                    "name": "title",
                    "description": "专业名称",
                    "required": True,
                    "data_type": "text",
                }
            ],
            "group_by": "category",
            "per_group_target_count": 10,
            "category_discovery_mode": "auto",
            "requested_categories": [],
            "category_examples": ["交通运输工程"],
        }
    )

    assert errors == []
    assert payload["group_by"] == "category"
    assert payload["per_group_target_count"] == 10
    assert payload["category_discovery_mode"] == "auto"
    assert payload["requested_categories"] == []
    assert payload["category_examples"] == ["交通运输工程"]


def test_validate_task_clarifier_payload_normalizes_invalid_grouping_combinations() -> None:
    payload, errors = validate_task_clarifier_payload(
        {
            "status": "ready",
            "intent": "collect",
            "task_description": "采集专业列表",
            "list_url": "https://example.com/majors",
            "fields": [
                {
                    "name": "title",
                    "description": "专业名称",
                    "required": True,
                    "data_type": "text",
                }
            ],
            "group_by": "none",
            "per_group_target_count": 10,
            "total_target_count": 0,
            "category_discovery_mode": "manual",
            "requested_categories": ["土木工程"],
            "category_examples": ["交通运输工程"],
        }
    )

    assert errors == []
    assert payload["group_by"] == "none"
    assert payload["per_group_target_count"] is None
    assert payload["total_target_count"] is None
    assert payload["category_discovery_mode"] == "auto"
    assert payload["requested_categories"] == []
    assert payload["category_examples"] == []
