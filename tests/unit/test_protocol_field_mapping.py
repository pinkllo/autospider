from __future__ import annotations


from autospider.common.protocol import (
    extract_json_dict_from_llm_payload,
    extract_response_text_from_llm_payload,
    parse_json_dict_from_llm,
    parse_protocol_message,
    summarize_llm_payload,
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


def test_parse_protocol_message_requires_explicit_action():
    assert parse_protocol_message({"args": {"mark_id": 1}}) is None
    assert parse_protocol_message({}) is None
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


def test_parse_json_dict_from_llm_rejects_broken_json_like_payload():
    text = """
    {
      "action": "extract",
      "args": {
        "kind": "field"
        "field_name": "招标项目名称"
      }
    }
    """
    assert parse_json_dict_from_llm(text) is None


class _FakeStructuredResponse:
    def __init__(self, *, content="", text="", additional_kwargs=None):
        self.content = content
        self.text = text
        self.additional_kwargs = additional_kwargs or {}
        self.response_metadata = {}


def test_extract_json_dict_from_llm_payload_reads_additional_kwargs_parsed():
    response = _FakeStructuredResponse(
        content="",
        additional_kwargs={"parsed": {"status": "ready", "list_url": "https://example.com", "fields": []}},
    )

    parsed = extract_json_dict_from_llm_payload(response)

    assert parsed == {"status": "ready", "list_url": "https://example.com", "fields": []}


def test_extract_response_text_from_llm_payload_prefers_text_attr():
    response = _FakeStructuredResponse(text='{"selected_indexes":[1],"reasoning":"最相关"}')

    assert extract_response_text_from_llm_payload(response) == '{"selected_indexes":[1],"reasoning":"最相关"}'


def test_extract_json_dict_from_llm_payload_reads_nested_response_metadata_message():
    response = _FakeStructuredResponse(
        content="",
        additional_kwargs={},
    )
    response.response_metadata = {
        "message": {
            "content": [
                {
                    "type": "output_text",
                    "text": '{"status":"ready","list_url":"https://example.com","fields":[]}',
                }
            ]
        }
    }

    parsed = extract_json_dict_from_llm_payload(response)

    assert parsed == {"status": "ready", "list_url": "https://example.com", "fields": []}


def test_extract_response_text_from_llm_payload_reads_nested_message_blocks():
    response = _FakeStructuredResponse(
        content=[],
        additional_kwargs={
            "message": {
                "content": [
                    {
                        "type": "output_text",
                        "text": '{"selected_indexes":[1],"reasoning":"最相关"}',
                    }
                ]
            }
        },
    )

    assert extract_response_text_from_llm_payload(response) == '{"selected_indexes":[1],"reasoning":"最相关"}'


def test_summarize_llm_payload_includes_nested_shape():
    response = _FakeStructuredResponse(
        content=[],
        additional_kwargs={
            "message": {
                "content": [
                    {
                        "type": "output_text",
                        "text": '{"status":"ready"}',
                    }
                ]
            }
        },
    )

    summary = summarize_llm_payload(response)

    assert summary["payload_type"] == "_FakeStructuredResponse"
    assert "shape" in summary
    assert summary["shape"]["additional_kwargs"]["message"]["content"]["items"][0]["type"] == "output_text"

