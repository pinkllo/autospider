from __future__ import annotations

from autospider.common.llm_contracts import (
    validate_protocol_message_payload,
    validate_task_clarifier_payload,
)
from autospider.common.protocol import parse_protocol_message


def test_validate_task_clarifier_payload_normalizes_ready_payload():
    payload, errors = validate_task_clarifier_payload(
        {
            "status": "ready",
            "intent": "采集公告",
            "confidence": 0.9,
            "task_description": "采集公告详情",
            "list_url": " https://example.com/list ",
            "fields": [
                {
                    "name": "title",
                    "description": "标题",
                    "required": True,
                    "data_type": "text",
                    "example": "  示例标题  ",
                }
            ],
            "target_url_count": "10",
            "consumer_concurrency": "3",
            "field_explore_count": 0,
        }
    )

    assert errors == []
    assert payload["status"] == "ready"
    assert payload["list_url"] == "https://example.com/list"
    assert payload["fields"][0]["example"] == "示例标题"
    assert payload["target_url_count"] == 10
    assert payload["consumer_concurrency"] == 3
    assert payload["field_explore_count"] is None


def test_validate_task_clarifier_payload_reports_invalid_field():
    payload, errors = validate_task_clarifier_payload(
        {
            "status": "ready",
            "task_description": "采集公告详情",
            "list_url": "https://example.com/list",
            "fields": [{"name": "", "description": "标题"}],
        }
    )

    assert payload == {}
    assert errors
    assert any("field name cannot be empty" in message for message in errors)


def test_validate_protocol_message_payload_rejects_invalid_type_action():
    payload, errors = validate_protocol_message_payload(
        action="type",
        args={"target_text": "搜索框"},
    )

    assert payload is None
    assert errors
    assert any("type requires text" in message for message in errors)


def test_parse_protocol_message_rejects_invalid_scroll_delta():
    parsed = parse_protocol_message(
        {
            "action": "scroll",
            "args": {"scroll_delta": [0]},
        }
    )

    assert parsed is None


def test_parse_protocol_message_keeps_legacy_action_inference():
    parsed_click = parse_protocol_message({"args": {"target_text": "佛教部"}})
    parsed_type = parse_protocol_message({"args": {"target_text": "搜索框", "text": "佛教"}})

    assert parsed_click is not None
    assert parsed_click["action"] == "click"
    assert parsed_type is not None
    assert parsed_type["action"] == "type"
