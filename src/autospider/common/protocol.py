"""统一的 LLM 输出协议（protocol v1）解析与兼容映射。

修改原因：
- 之前项目中存在多套“工具/动作协议”（decider、url_collector、field_extractor、disambiguate 等），
  LLM 输出结构不一致，导致解析与维护成本高、鲁棒性差。
- 现在统一为一套大协议：`autospider.protocol.v1`，并在代码侧提供兼容映射，
  让旧逻辑无需大改也能接入新协议。
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field


PROTOCOL_V1: str = "autospider.protocol.v1"


class ProtocolMessage(BaseModel):
    """LLM 统一协议消息（v1）"""

    protocol: Literal["autospider.protocol.v1"] = Field(...)
    action: str = Field(..., description="动作类型（统一协议中的 action）")
    args: dict[str, Any] = Field(default_factory=dict, description="动作参数（统一协议中的 args）")
    thinking: str = Field(default="", description="思考过程（可选）")


def _strip_code_fences(text: str) -> str:
    if "```" not in text:
        return text
    cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE)
    return cleaned.replace("```", "").strip()


def _extract_json_object(text: str) -> str | None:
    match = re.search(r"\{[\s\S]*\}", text)
    return match.group(0) if match else None


def _normalize_quotes(text: str) -> str:
    # 常见的中文引号/全角符号替换，避免 LLM 输出“看起来像 JSON 但其实不是”的情况
    return (
        text.replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
        .replace("\u00a0", " ")
    )


def _cleanup_json_text(json_text: str) -> str:
    # 修复常见的 JSON 问题：末尾多余逗号
    cleaned = re.sub(r",\s*}", "}", json_text)
    cleaned = re.sub(r",\s*]", "]", cleaned)
    return cleaned


def _extract_balanced_object(text: str, start_index: int) -> str | None:
    """从 start_index 指向的 '{' 开始，提取一个按括号匹配的 JSON 对象子串（忽略字符串内的括号）。"""
    if start_index < 0 or start_index >= len(text) or text[start_index] != "{":
        return None

    depth = 0
    in_string = False
    escape = False

    for idx in range(start_index, len(text)):
        ch = text[idx]

        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            depth -= 1
            if depth == 0:
                return text[start_index : idx + 1]
            continue

    return None


def _iter_json_object_candidates(text: str) -> list[str]:
    """提取可能的 JSON 对象候选（优先使用括号匹配，避免贪婪正则跨越多个对象）。"""
    candidates: list[str] = []
    for m in re.finditer(r"\{", text):
        obj = _extract_balanced_object(text, m.start())
        if obj and obj not in candidates:
            candidates.append(obj)
    return candidates


def _salvage_json_like_dict(text: str) -> dict[str, Any] | None:
    """当 JSON 不可解析时，尽力从文本中“抢救”出关键信息。"""
    if not text:
        return None

    cleaned = _normalize_quotes(_strip_code_fences(text))

    def _pick_str(key: str) -> str | None:
        m = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"]*)"', cleaned)
        return m.group(1) if m else None

    def _pick_int(key: str) -> int | None:
        m = re.search(rf'"{re.escape(key)}"\s*:\s*"?(?P<v>\d+)"?', cleaned)
        if not m:
            return None
        try:
            return int(m.group("v"))
        except ValueError:
            return None

    action = _pick_str("action")
    if not action:
        return None

    protocol = _pick_str("protocol")
    thinking = _pick_str("thinking") or ""

    # args 尝试：先截取 args 对象并解析；失败再从全局粗略提取
    args: dict[str, Any] = {}
    args_start = re.search(r'"args"\s*:\s*\{', cleaned)
    if args_start:
        obj = _extract_balanced_object(cleaned, args_start.end() - 1)
        if obj:
            try:
                args = json.loads(_cleanup_json_text(obj))
            except Exception:
                args = {}

    if not args:
        for k in ["mark_id", "target_text", "text", "key", "url", "reasoning", "field_name", "field_value", "location_description"]:
            v = _pick_str(k)
            if v is not None:
                args[k] = v
        mark_id = _pick_int("mark_id")
        if mark_id is not None:
            args["mark_id"] = mark_id

        # scroll_delta 形如 [0,500]
        sd = re.search(r'"scroll_delta"\s*:\s*\[\s*(-?\d+)\s*,\s*(-?\d+)\s*\]', cleaned)
        if sd:
            args["scroll_delta"] = [int(sd.group(1)), int(sd.group(2))]

    if protocol == PROTOCOL_V1:
        return {"protocol": protocol, "action": action, "args": args, "thinking": thinking}

    # 非 v1 情况也返回“尽力而为”的 dict，让上层还能走 legacy 解析
    out: dict[str, Any] = {"action": action}
    if thinking:
        out["thinking"] = thinking
    out.update(args)
    return out


def parse_json_dict_from_llm(text: str) -> dict[str, Any] | None:
    """从 LLM 文本中提取并解析 JSON 对象"""
    cleaned = _normalize_quotes(_strip_code_fences(text or ""))

    # 1) 优先：使用括号匹配提取候选 JSON 对象，逐个尝试解析
    for cand in _iter_json_object_candidates(cleaned):
        try:
            data = json.loads(_cleanup_json_text(cand))
        except Exception:
            continue
        if isinstance(data, dict):
            return data

    # 2) 兼容：旧逻辑的贪婪匹配（少数情况下括号匹配提不到）
    json_text = _extract_json_object(cleaned)
    if json_text:
        try:
            data = json.loads(_cleanup_json_text(json_text))
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    # 3) 最后兜底：抢救式解析（可能不是严格 JSON）
    return _salvage_json_like_dict(cleaned)


def is_protocol_v1(data: dict[str, Any] | None) -> bool:
    return bool(data) and data.get("protocol") == PROTOCOL_V1 and "action" in data


def as_protocol_v1(data: dict[str, Any]) -> ProtocolMessage | None:
    if not is_protocol_v1(data):
        return None
    try:
        return ProtocolMessage.model_validate(data)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 兼容映射（把大协议映射为旧代码期望的结构）
# ---------------------------------------------------------------------------


def protocol_to_legacy_agent_action(data: dict[str, Any]) -> dict[str, Any]:
    """映射到通用 Agent（Action）旧扁平字段结构"""
    if not is_protocol_v1(data):
        return data

    msg = as_protocol_v1(data)
    if msg is None:
        return data

    args = msg.args or {}
    action = (msg.action or "").lower()

    legacy: dict[str, Any] = {
        "action": action,
        "thinking": msg.thinking or args.get("thinking") or args.get("reasoning") or "",
    }

    # 常见字段扁平化
    for key in ["mark_id", "target_text", "text", "key", "url", "timeout_ms", "expectation"]:
        if key in args and args[key] is not None:
            legacy[key] = args[key]

    if "scroll_delta" in args and isinstance(args["scroll_delta"], (list, tuple)) and len(args["scroll_delta"]) == 2:
        legacy["scroll_delta"] = list(args["scroll_delta"])

    return legacy


def protocol_to_legacy_url_decision(data: dict[str, Any]) -> dict[str, Any]:
    """映射到 URLCollector 探索阶段旧决策结构（select_detail_links / click_to_enter / ...）"""
    if not is_protocol_v1(data):
        return data

    msg = as_protocol_v1(data)
    if msg is None:
        return data

    action = (msg.action or "").lower()
    args = msg.args or {}
    purpose = (args.get("purpose") or "").lower()
    reasoning = args.get("reasoning") or msg.thinking or ""

    if action == "select" and purpose in {"detail_links", "detail_link", "detail"}:
        items = args.get("items") or []
        mark_id_text_map: dict[str, str] = {}
        for it in items:
            if not isinstance(it, dict):
                continue
            mid = it.get("mark_id")
            text = it.get("text") or it.get("target_text") or ""
            if mid is None or not text:
                continue
            mark_id_text_map[str(mid)] = str(text)

        return {
            "action": "select_detail_links",
            "mark_id_text_map": mark_id_text_map,
            "reasoning": reasoning,
        }

    if action == "click":
        return {
            "action": "click_to_enter",
            "mark_id": args.get("mark_id"),
            "target_text": args.get("target_text") or "",
            "reasoning": reasoning,
        }

    if action == "scroll":
        return {"action": "scroll_down", "reasoning": reasoning}

    if action == "report" and (args.get("kind") or "").lower() == "page_kind":
        if (args.get("page_kind") or "").lower() == "detail":
            return {"action": "current_is_detail", "reasoning": reasoning}

    return data


def protocol_to_legacy_pagination_result(data: dict[str, Any]) -> dict[str, Any]:
    """映射分页按钮识别旧结构（found/mark_id/target_text）"""
    if not is_protocol_v1(data):
        return data

    msg = as_protocol_v1(data)
    if msg is None:
        return data

    args = msg.args or {}
    if (msg.action or "").lower() != "select":
        return data

    purpose = (args.get("purpose") or "").lower()
    if purpose not in {"pagination_next", "next_page"}:
        return data

    found = bool(args.get("found", True))
    item = args.get("item")
    if not isinstance(item, dict):
        items = args.get("items") or []
        item = items[0] if items and isinstance(items[0], dict) else None

    mark_id = item.get("mark_id") if isinstance(item, dict) else None
    target_text = (item.get("text") if isinstance(item, dict) else None) or args.get("target_text") or ""

    return {
        "found": found,
        "mark_id": mark_id,
        "target_text": target_text,
        "reasoning": args.get("reasoning") or msg.thinking or "",
    }


def protocol_to_legacy_jump_widget_result(data: dict[str, Any]) -> dict[str, Any]:
    """映射跳页控件识别旧结构（found/input_mark_id/button_mark_id/...）"""
    if not is_protocol_v1(data):
        return data

    msg = as_protocol_v1(data)
    if msg is None:
        return data

    args = msg.args or {}
    if (msg.action or "").lower() != "select":
        return data

    purpose = (args.get("purpose") or "").lower()
    if purpose not in {"jump_widget", "page_jump"}:
        return data

    found = bool(args.get("found", True))
    input_obj = args.get("input") if isinstance(args.get("input"), dict) else {}
    button_obj = args.get("button") if isinstance(args.get("button"), dict) else {}

    return {
        "found": found,
        "input_mark_id": input_obj.get("mark_id"),
        "button_mark_id": button_obj.get("mark_id"),
        "input_text": input_obj.get("text") or "",
        "button_text": button_obj.get("text") or "",
        "reasoning": args.get("reasoning") or msg.thinking or "",
    }


def protocol_to_legacy_field_nav_decision(data: dict[str, Any], field_name: str) -> dict[str, Any]:
    """映射字段提取“导航阶段”旧结构（found_field/field_not_exist/click/type/press/scroll_down）"""
    if not is_protocol_v1(data):
        return data

    msg = as_protocol_v1(data)
    if msg is None:
        return data

    action = (msg.action or "").lower()
    args = msg.args or {}

    if action in {"click", "type", "press"}:
        legacy = {"action": action, "reasoning": args.get("reasoning") or msg.thinking or ""}
        for key in ["mark_id", "target_text", "text", "key"]:
            if key in args and args[key] is not None:
                legacy[key] = args[key]
        return legacy

    if action == "scroll":
        return {"action": "scroll_down", "reasoning": args.get("reasoning") or msg.thinking or ""}

    if action == "extract" and (args.get("kind") or "").lower() == "field":
        # 统一：字段结果也走 extract；这里将其映射为旧的导航返回格式
        reported_name = str(args.get("field_name") or "").strip()
        expected_name = str(field_name).strip()
        if reported_name and reported_name != expected_name:
            # 字段名不匹配时直接透传，交由上层决定是否重试
            return data

        found = bool(args.get("found", False))
        if found:
            return {
                "action": "found_field",
                "field_text": args.get("field_value") or args.get("field_text") or "",
                "field_value": args.get("field_value") or "",
                "mark_id": args.get("mark_id"),
                "target_text": args.get("target_text") or "",
                "confidence": args.get("confidence", 0.0),
                "reasoning": args.get("reasoning") or msg.thinking or "",
                "location_description": args.get("location_description") or "",
            }

        return {
            "action": "field_not_exist",
            "reasoning": args.get("reasoning") or msg.thinking or "",
        }

    return data


def protocol_to_legacy_field_extract_result(data: dict[str, Any], field_name: str) -> dict[str, Any]:
    """映射字段提取“识别文本阶段”旧结构（found/field_value/confidence/...）"""
    if not is_protocol_v1(data):
        return data

    msg = as_protocol_v1(data)
    if msg is None:
        return data

    args = msg.args or {}
    if (msg.action or "").lower() != "extract" or (args.get("kind") or "").lower() != "field":
        return data

    reported_name = str(args.get("field_name") or "").strip()
    expected_name = str(field_name).strip()
    if reported_name and reported_name != expected_name:
        return data

    found = bool(args.get("found", False))
    return {
        "found": found,
        "field_value": args.get("field_value") or "",
        "confidence": args.get("confidence", 0.0),
        "location_description": args.get("location_description") or "",
        "reasoning": args.get("reasoning") or msg.thinking or "",
        "mark_id": args.get("mark_id"),
        "target_text": args.get("target_text") or "",
    }


def protocol_to_legacy_selected_mark(data: dict[str, Any]) -> dict[str, Any]:
    """映射“从多个候选中选择一个”的旧结构（selected_mark_id）"""
    if not is_protocol_v1(data):
        return data

    msg = as_protocol_v1(data)
    if msg is None:
        return data

    args = msg.args or {}
    if (msg.action or "").lower() != "select":
        return data

    selected = args.get("selected_mark_id")
    if selected is None:
        item = args.get("item")
        if isinstance(item, dict):
            selected = item.get("mark_id")
        else:
            items = args.get("items") or []
            if items and isinstance(items[0], dict):
                selected = items[0].get("mark_id")

    return {
        "selected_mark_id": selected,
        "reasoning": args.get("reasoning") or msg.thinking or "",
    }
