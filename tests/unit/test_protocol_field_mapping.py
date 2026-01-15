from __future__ import annotations


from autospider.common.protocol import (
    parse_json_dict_from_llm,
    parse_protocol_message,
    protocol_to_legacy_field_extract_result,
    protocol_to_legacy_field_nav_decision,
)


def test_field_nav_decision_extract_with_args_maps_to_found_field():
    data = {
        "action": "extract",
        "args": {
            "kind": "field",
            "field_name": "招标项目名称",
            "found": True,
            "field_value": "前海综合交通枢纽上盖项目深铁前海国际枢纽中心T2栋园林景观工程",
            "confidence": 0.98,
        },
    }
    out = protocol_to_legacy_field_nav_decision(data, "招标项目名称")
    assert out["action"] == "found_field"
    assert out["field_value"]


def test_field_nav_decision_extract_with_args_missing_kind_is_mapped():
    data = {
        "action": "extract",
        "args": {
            "field_name": "招标项目名称",
            "found": True,
            "field_value": "示例值",
        },
    }
    out = protocol_to_legacy_field_nav_decision(data, "招标项目名称")
    assert out["action"] == "found_field"
    assert out["field_value"] == "示例值"


def test_field_nav_decision_action_with_trailing_spaces_is_mapped():
    data = {
        "action": "extract ",
        "args": {
            "kind": "field",
            "field_name": "招标项目名称",
            "found": True,
            "field_value": "示例值",
        },
    }
    out = protocol_to_legacy_field_nav_decision(data, "招标项目名称")
    assert out["action"] == "found_field"
    assert out["field_value"] == "示例值"


def test_field_nav_decision_extract_field_name_with_zero_width_char_is_mapped():
    data = {
        "action": "extract",
        "args": {
            "kind": "field",
            "field_name": "招标项目名称\u200b",
            "found": True,
            "field_value": "示例值",
        },
    }
    out = protocol_to_legacy_field_nav_decision(data, "招标项目名称")
    assert out["action"] == "found_field"
    assert out["field_value"] == "示例值"


def test_field_nav_decision_extract_flattened_maps_to_found_field():
    data = {
        "action": "extract",
        "kind": "field",
        "field_name": "招标项目名称",
        "found": True,
        "field_value": "示例值",
        "confidence": 0.98,
    }
    out = protocol_to_legacy_field_nav_decision(data, "招标项目名称")
    assert out["action"] == "found_field"
    assert out["field_value"] == "示例值"


def test_field_nav_decision_extract_field_name_mismatch_passthrough():
    data = {
        "action": "extract",
        "kind": "field",
        "field_name": "其他字段",
        "found": True,
        "field_value": "示例值",
    }
    out = protocol_to_legacy_field_nav_decision(data, "招标项目名称")
    assert out == data


def test_field_nav_decision_extract_found_false_maps_to_not_exist():
    data = {
        "action": "extract",
        "kind": "field",
        "field_name": "招标项目名称",
        "found": False,
        "reasoning": "页面未包含该字段",
    }
    out = protocol_to_legacy_field_nav_decision(data, "招标项目名称")
    assert out["action"] == "field_not_exist"


def test_field_extract_result_flattened_is_mapped():
    data = {
        "action": "extract",
        "kind": "field",
        "field_name": "招标项目名称",
        "found": True,
        "field_value": "示例值",
        "confidence": 0.5,
    }
    out = protocol_to_legacy_field_extract_result(data, "招标项目名称")
    assert out["found"] is True
    assert out["field_value"] == "示例值"


def test_field_extract_result_v1_without_kind_is_mapped():
    data = {
        "action": "extract",
        "args": {
            "field_name": "招标项目名称",
            "found": True,
            "field_value": "示例值",
        },
    }
    out = protocol_to_legacy_field_extract_result(data, "招标项目名称")
    assert out["found"] is True
    assert out["field_value"] == "示例值"


def test_field_extract_result_action_with_trailing_spaces_is_mapped():
    data = {
        "action": "extract ",
        "args": {
            "kind": "field",
            "field_name": "招标项目名称",
            "found": True,
            "field_value": "示例值",
        },
    }
    out = protocol_to_legacy_field_extract_result(data, "招标项目名称")
    assert out["found"] is True
    assert out["field_value"] == "示例值"


def test_parse_json_dict_from_llm_salvages_found_from_broken_json():
    # 修改原因：真实运行中出现过 `"found"\n:true` 这种不严格 JSON，json.loads 失败会走 salvage。
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

    nav = protocol_to_legacy_field_nav_decision(parsed, "招标项目名称")
    assert nav["action"] == "found_field"
    assert nav["field_value"] == "示例值"

    res = protocol_to_legacy_field_extract_result(parsed, "招标项目名称")
    assert res["found"] is True
    assert res["field_value"] == "示例值"


def test_parse_protocol_message_normalizes_action_and_found():
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
    assert parsed["args"]["found"] is False
