from __future__ import annotations


from autospider.common.protocol import (
    parse_json_dict_from_llm,
    parse_protocol_message,
)


def test_parse_protocol_message_normalizes_action():
    text = """
    {
      "action": " EXTRACT ",
      "args": {
        "kind": "field",
        "field_name": "招标项目名称",
        "found": "false",
        "field_value": "示例值"
      }
    }
    """
    parsed = parse_protocol_message(text)
    assert parsed is not None
    assert parsed["action"] == "extract"
    assert parsed["args"]["found"] == "false"


def test_parse_protocol_message_from_dict_payload():
    parsed = parse_protocol_message({"action": " CLICK ", "args": {"mark_id": 12}})
    assert parsed is not None
    assert parsed["action"] == "click"
    assert parsed["args"]["mark_id"] == 12


def test_parse_protocol_message_missing_action_returns_none():
    assert parse_protocol_message({"args": {"mark_id": 1}}) is None
    assert parse_protocol_message(None) is None


def test_parse_json_dict_from_llm_parses_code_fence_with_trailing_comma():
    text = """
    ```json
    {
      "action": "click",
      "args": {"mark_id": 3,}
    }
    ```
    """
    parsed = parse_json_dict_from_llm(text)
    assert isinstance(parsed, dict)
    assert parsed["action"] == "click"
    assert parsed["args"]["mark_id"] == 3


def test_parse_json_dict_from_llm_salvages_broken_json_like_found_bool():
    text = """
    {
      "action": "extract",
      "args": {
        "kind": "field",
        "field_name": "招标项目名称",
        "found"
        :true,
        "field_value": "示例值",
        "confidence": 0.98
      }
    }
    """
    parsed = parse_json_dict_from_llm(text)
    assert isinstance(parsed, dict)
    assert parsed["action"] == "extract"
    assert parsed["args"]["found"] is True
    assert parsed["args"]["field_value"] == "示例值"
