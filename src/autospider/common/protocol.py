"""统一的 LLM 输出协议解析与兼容映射（protocol 字段可选）。"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

PROTOCOL_V1: str = "autospider.protocol.v1"


class ProtocolMessage(BaseModel):
    """LLM 统一协议消息（v1，可省略 protocol 字段）"""

    protocol: Literal["autospider.protocol.v1"] = Field(default=PROTOCOL_V1)
    action: str = Field(..., description="动作类型")
    args: dict[str, Any] = Field(default_factory=dict, description="动作参数")
    thinking: str = Field(default="", description="思考过程（可选）")


# ---------------------------------------------------------------------------
# 文本清理工具
# ---------------------------------------------------------------------------

_QUOTE_TRANS = str.maketrans(
    {
        0x201C: '"',  # 左双引号 "
        0x201D: '"',  # 右双引号 "
        0x2018: "'",  # 左单引号 '
        0x2019: "'",  # 右单引号 '
        0x00A0: " ",  # 不间断空格
    }
)


def _normalize_quotes(text: str) -> str:
    """替换中文引号/全角符号为标准ASCII字符"""
    return text.translate(_QUOTE_TRANS)


def _strip_code_fences(text: str) -> str:
    """移除 Markdown 代码块标记"""
    if "```" not in text:
        return text
    return re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).replace("```", "").strip()


def _cleanup_json_text(json_text: str) -> str:
    """修复常见 JSON 问题：末尾多余逗号"""
    return re.sub(r",(\s*[}\]])", r"\1", json_text)


def _normalize_field_name(value: str | None) -> str:
    """规范化字段名：去除空白和不可见字符"""
    if not value:
        return ""
    return "".join(
        ch
        for ch in _normalize_quotes(str(value))
        if not ch.isspace() and unicodedata.category(ch) != "Cf"
    ).strip()


def _normalize_action(value: Any | None) -> str:
    """规范化 action：小写去首尾空白"""
    return str(value).strip().lower() if value else ""


def _coerce_bool(value: Any | None, default: bool | None = None) -> bool | None:
    """将各种 bool 表示形式统一转换为 Python bool"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "yes", "y", "1"}:
            return True
        if v in {"false", "no", "n", "0"}:
            return False
    return default


# ---------------------------------------------------------------------------
# JSON 提取与解析
# ---------------------------------------------------------------------------


def _extract_balanced_object(text: str, start: int) -> str | None:
    """从指定位置提取括号匹配的 JSON 对象"""
    if start < 0 or start >= len(text) or text[start] != "{":
        return None

    depth, in_string, escape = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            escape = not escape and ch == "\\"
            if not escape and ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _iter_json_candidates(text: str) -> list[str]:
    """提取所有可能的 JSON 对象候选"""
    seen: set[str] = set()
    return [
        obj
        for m in re.finditer(r"\{", text)
        if (obj := _extract_balanced_object(text, m.start())) and obj not in seen and not seen.add(obj)  # type: ignore
    ]


@dataclass
class _FieldExtractor:
    """从文本中提取 JSON 字段值的辅助类"""

    text: str

    def _match(self, pattern: str) -> re.Match[str] | None:
        return re.search(pattern, self.text, flags=re.IGNORECASE)

    def string(self, key: str) -> str | None:
        m = self._match(rf'"{re.escape(key)}"\s*:\s*"([^"]*)"')
        return m.group(1) if m else None

    def integer(self, key: str) -> int | None:
        m = self._match(rf'"{re.escape(key)}"\s*:\s*"?(\d+)"?')
        try:
            return int(m.group(1)) if m else None
        except ValueError:
            return None

    def boolean(self, key: str) -> bool | None:
        m = self._match(rf'"{re.escape(key)}"\s*:\s*(true|false|"true"|"false"|1|0)')
        return _coerce_bool(m.group(1).strip('"')) if m else None

    def floating(self, key: str) -> float | None:
        m = self._match(rf'"{re.escape(key)}"\s*:\s*(-?\d+(?:\.\d+)?)')
        try:
            return float(m.group(1)) if m else None
        except ValueError:
            return None


def _salvage_json_like_dict(text: str) -> dict[str, Any] | None:
    """尽力从格式错误的文本中抢救关键信息"""
    if not text:
        return None

    cleaned = _normalize_quotes(_strip_code_fences(text))
    ext = _FieldExtractor(cleaned)

    action = ext.string("action")
    if not action:
        return None

    # 提取 args 对象
    args: dict[str, Any] = {}
    args_match = re.search(r'"args"\s*:\s*\{', cleaned)
    if args_match and (obj := _extract_balanced_object(cleaned, args_match.end() - 1)):
        try:
            args = json.loads(_cleanup_json_text(obj))
        except Exception:
            pass

    # args 为空时提取常见字段
    if not args:
        for k in [
            "kind",
            "target_text",
            "text",
            "key",
            "url",
            "reasoning",
            "field_name",
            "field_value",
            "location_description",
        ]:
            if (v := ext.string(k)) is not None:
                args[k] = v
        if (v := ext.integer("mark_id")) is not None:
            args["mark_id"] = v
        if (v := ext.boolean("found")) is not None:
            args["found"] = v
        if (v := ext.floating("confidence")) is not None:
            args["confidence"] = v
        if sd := re.search(r'"scroll_delta"\s*:\s*\[\s*(-?\d+)\s*,\s*(-?\d+)\s*\]', cleaned):
            args["scroll_delta"] = [int(sd.group(1)), int(sd.group(2))]

    # 构建输出
    out: dict[str, Any] = {"action": action}
    if thinking := ext.string("thinking"):
        out["thinking"] = thinking
    if protocol := ext.string("protocol"):
        out["protocol"] = protocol

    if protocol == PROTOCOL_V1 or args_match:
        out["args"] = args
    else:
        out.update(args)
    return out


def parse_json_dict_from_llm(text: str) -> dict[str, Any] | None:
    """从 LLM 文本中提取并解析 JSON 对象"""
    cleaned = _normalize_quotes(_strip_code_fences(text or ""))

    # 优先：括号匹配提取
    for cand in _iter_json_candidates(cleaned):
        try:
            if isinstance(data := json.loads(_cleanup_json_text(cand)), dict):
                return data
        except Exception:
            continue

    # 兼容：贪婪正则匹配
    if match := re.search(r"\{[\s\S]*\}", cleaned):
        try:
            if isinstance(data := json.loads(_cleanup_json_text(match.group(0))), dict):
                return data
        except Exception:
            pass

    # 兜底：抢救式解析
    return _salvage_json_like_dict(cleaned)


# ---------------------------------------------------------------------------
# 协议解析核心
# ---------------------------------------------------------------------------


def _merge_args_with_top_level(data: dict[str, Any]) -> dict[str, Any]:
    """合并 args 与顶层字段，规范化常见字段类型"""
    raw_args = data.get("args") if isinstance(data.get("args"), dict) else {}
    merged = dict(raw_args)

    for key, value in data.items():
        if key not in {"action", "args", "protocol", "thinking"} and merged.get(key) is None:
            merged[key] = value

    # 规范化常见字段
    if merged.get("kind") is not None:
        merged["kind"] = str(merged["kind"]).strip().lower()
    if "found" in merged:
        merged["found"] = _coerce_bool(merged.get("found"))
    for field, conv in [("confidence", float), ("mark_id", int)]:
        if merged.get(field) is not None:
            try:
                merged[field] = conv(merged[field])
            except (TypeError, ValueError):
                pass
    return merged


def parse_protocol_message(payload: str | dict[str, Any] | None) -> dict[str, Any] | None:
    """统一协议解析入口：输出标准 action/args 结构"""
    if payload is None:
        return None

    data = payload if isinstance(payload, dict) else parse_json_dict_from_llm(payload)
    if not isinstance(data, dict) or not (action := _normalize_action(data.get("action"))):
        return None

    result: dict[str, Any] = {"action": action, "args": _merge_args_with_top_level(data)}
    if thinking := data.get("thinking") or data.get("reasoning"):
        result["thinking"] = thinking
    if protocol := data.get("protocol"):
        result["protocol"] = protocol
    return result


def is_protocol_v1(data: dict[str, Any] | None) -> bool:
    """检查是否为 v1 协议格式"""
    return bool(
        data
        and "action" in data
        and "args" in data
        and data.get("protocol", PROTOCOL_V1) == PROTOCOL_V1
    )


def as_protocol_v1(data: dict[str, Any]) -> ProtocolMessage | None:
    """转换为 ProtocolMessage 对象"""
    if not is_protocol_v1(data):
        return None
    try:
        return ProtocolMessage.model_validate(
            {**data, "protocol": PROTOCOL_V1, "args": data.get("args", {})}
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 兼容映射辅助
# ---------------------------------------------------------------------------


@dataclass
class _ProtocolParts:
    """协议解析后的核心部分"""

    action: str
    args: dict[str, Any]
    thinking: str

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "_ProtocolParts":
        if msg := as_protocol_v1(data):
            return cls(_normalize_action(msg.action), msg.args or {}, msg.thinking or "")
        return cls(
            _normalize_action(data.get("action")),
            data.get("args") if isinstance(data.get("args"), dict) else {},
            data.get("thinking") or data.get("reasoning") or "",
        )

    def get_reasoning(self) -> str:
        return self.args.get("reasoning") or self.thinking


def _field_names_match(reported: str | None, expected: str) -> bool:
    """检查字段名是否匹配（支持包含关系）"""
    r, e = _normalize_field_name(reported), _normalize_field_name(expected)
    return not r or not e or r == e or r in e or e in r


def _extract_item_from_args(args: dict[str, Any]) -> dict[str, Any] | None:
    """从 args 中提取 item 对象"""
    if isinstance(item := args.get("item"), dict):
        return item
    if (items := args.get("items")) and isinstance(items[0], dict):
        return items[0]
    return None


# ---------------------------------------------------------------------------
# 兼容映射函数
# ---------------------------------------------------------------------------


def protocol_to_legacy_agent_action(data: dict[str, Any]) -> dict[str, Any]:
    """映射到通用 Agent 旧扁平字段结构"""
    if not is_protocol_v1(data):
        return data

    parts = _ProtocolParts.from_data(data)
    legacy: dict[str, Any] = {"action": parts.action, "thinking": parts.get_reasoning()}

    for key in ["mark_id", "target_text", "text", "key", "url", "timeout_ms", "expectation"]:
        if parts.args.get(key) is not None:
            legacy[key] = parts.args[key]

    if isinstance(sd := parts.args.get("scroll_delta"), (list, tuple)) and len(sd) == 2:
        legacy["scroll_delta"] = list(sd)
    return legacy


def protocol_to_legacy_url_decision(data: dict[str, Any]) -> dict[str, Any]:
    """映射到 URLCollector 探索阶段旧决策结构"""
    if not is_protocol_v1(data):
        return data

    parts = _ProtocolParts.from_data(data)
    purpose = (parts.args.get("purpose") or "").lower()
    reasoning = parts.get_reasoning()

    if parts.action == "select" and purpose in {"detail_links", "detail_link", "detail"}:
        mark_id_text_map = {
            str(it["mark_id"]): str(it.get("text") or it.get("target_text") or "")
            for it in parts.args.get("items") or []
            if isinstance(it, dict)
            and it.get("mark_id") is not None
            and (it.get("text") or it.get("target_text"))
        }
        return {
            "action": "select_detail_links",
            "mark_id_text_map": mark_id_text_map,
            "reasoning": reasoning,
        }

    if parts.action == "click":
        return {
            "action": "click_to_enter",
            "mark_id": parts.args.get("mark_id"),
            "target_text": parts.args.get("target_text") or "",
            "reasoning": reasoning,
        }

    if parts.action == "scroll":
        return {"action": "scroll_down", "reasoning": reasoning}

    if (
        parts.action == "report"
        and (parts.args.get("kind") or "").lower() == "page_kind"
        and (parts.args.get("page_kind") or "").lower() == "detail"
    ):
        return {"action": "current_is_detail", "reasoning": reasoning}

    return data


def protocol_to_legacy_pagination_result(data: dict[str, Any]) -> dict[str, Any]:
    """映射分页按钮识别旧结构"""
    if not is_protocol_v1(data):
        return data

    parts = _ProtocolParts.from_data(data)
    if parts.action != "select" or (parts.args.get("purpose") or "").lower() not in {
        "pagination_next",
        "next_page",
    }:
        return data

    item = _extract_item_from_args(parts.args)
    return {
        "found": bool(parts.args.get("found", True)),
        "mark_id": item.get("mark_id") if item else None,
        "target_text": (item.get("text") if item else None) or parts.args.get("target_text") or "",
        "reasoning": parts.get_reasoning(),
    }


def protocol_to_legacy_jump_widget_result(data: dict[str, Any]) -> dict[str, Any]:
    """映射跳页控件识别旧结构"""
    if not is_protocol_v1(data):
        return data

    parts = _ProtocolParts.from_data(data)
    if parts.action != "select" or (parts.args.get("purpose") or "").lower() not in {
        "jump_widget",
        "page_jump",
    }:
        return data

    input_obj = parts.args.get("input") if isinstance(parts.args.get("input"), dict) else {}
    button_obj = parts.args.get("button") if isinstance(parts.args.get("button"), dict) else {}
    return {
        "found": bool(parts.args.get("found", True)),
        "input_mark_id": input_obj.get("mark_id"),
        "button_mark_id": button_obj.get("mark_id"),
        "input_text": input_obj.get("text") or "",
        "button_text": button_obj.get("text") or "",
        "reasoning": parts.get_reasoning(),
    }


def _is_field_extract_like(merged: dict[str, Any]) -> bool:
    """判断是否为字段提取相关动作"""
    kind = str(merged.get("kind") or "").lower().strip()
    if kind == "field":
        return True
    if kind:
        return False
    return any(k in merged for k in ("field_name", "field_value", "field_text", "found"))


def _build_found_field_result(merged: dict[str, Any], reasoning: str) -> dict[str, Any]:
    """构建 found_field 返回结构"""
    return {
        "action": "found_field",
        "field_text": merged.get("field_value") or merged.get("field_text") or "",
        "field_value": merged.get("field_value") or "",
        "mark_id": merged.get("mark_id"),
        "target_text": merged.get("target_text") or "",
        "confidence": merged.get("confidence", 0.0),
        "reasoning": reasoning,
        "location_description": merged.get("location_description") or "",
    }


def _process_flat_field_extract(data: dict[str, Any], field_name: str) -> dict[str, Any] | None:
    """处理扁平结构的字段提取"""
    args = data.get("args") if isinstance(data.get("args"), dict) else {}
    merged = {**data, **args}

    if not _is_field_extract_like(merged) or not _field_names_match(
        merged.get("field_name"), field_name
    ):
        return None

    found = _coerce_bool(merged.get("found"))
    if found is None:
        found = bool(merged.get("field_value") or merged.get("field_text"))

    reasoning = merged.get("reasoning") or merged.get("thinking") or ""
    return (
        _build_found_field_result(merged, reasoning)
        if found
        else {"action": "field_not_exist", "reasoning": reasoning}
    )


def protocol_to_legacy_field_nav_decision(data: dict[str, Any], field_name: str) -> dict[str, Any]:
    """映射字段提取"导航阶段"旧结构"""
    if not is_protocol_v1(data):
        if _normalize_action(data.get("action")) == "extract":
            if result := _process_flat_field_extract(data, field_name):
                return result
        return data

    parts = _ProtocolParts.from_data(data)

    # 处理导航动作
    if parts.action in {"click", "type", "press"}:
        legacy = {"action": parts.action, "reasoning": parts.get_reasoning()}
        for key in ["mark_id", "target_text", "text", "key"]:
            if parts.args.get(key) is not None:
                legacy[key] = parts.args[key]
        return legacy

    if parts.action == "scroll":
        return {"action": "scroll_down", "reasoning": parts.get_reasoning()}

    # 处理字段提取
    if parts.action == "extract":
        merged = {**data, **parts.args}
        if _is_field_extract_like(merged) and _field_names_match(
            parts.args.get("field_name"), field_name
        ):
            found = _coerce_bool(parts.args.get("found"))
            if found is None:
                found = bool(parts.args.get("field_value") or parts.args.get("field_text"))
            reasoning = parts.get_reasoning()
            return (
                _build_found_field_result(merged, reasoning)
                if found
                else {"action": "field_not_exist", "reasoning": reasoning}
            )

    return data


def protocol_to_legacy_field_extract_result(
    data: dict[str, Any], field_name: str
) -> dict[str, Any]:
    """映射字段提取"识别文本阶段"旧结构"""

    def _build_extract_result(
        merged: dict[str, Any], found: bool, reasoning: str
    ) -> dict[str, Any]:
        return {
            "found": found,
            "field_value": merged.get("field_value") or "",
            "confidence": merged.get("confidence", 0.0),
            "location_description": merged.get("location_description") or "",
            "reasoning": reasoning,
            "mark_id": merged.get("mark_id"),
            "target_text": merged.get("target_text") or "",
        }

    if not is_protocol_v1(data):
        action = _normalize_action(data.get("action"))
        if action and action != "extract":
            return data

        args = data.get("args") if isinstance(data.get("args"), dict) else {}
        merged = {**data, **args}

        if not _is_field_extract_like(merged) or not _field_names_match(
            merged.get("field_name"), field_name
        ):
            return data

        found = _coerce_bool(merged.get("found"))
        if found is None:
            found = bool(merged.get("field_value") or merged.get("field_text"))
        return _build_extract_result(
            merged, found, merged.get("reasoning") or merged.get("thinking") or ""
        )

    parts = _ProtocolParts.from_data(data)
    if parts.action != "extract":
        return data

    merged = {**data, **parts.args}
    if not _is_field_extract_like(merged) or not _field_names_match(
        parts.args.get("field_name"), field_name
    ):
        return data

    found = _coerce_bool(parts.args.get("found"))
    if found is None:
        found = bool(parts.args.get("field_value") or parts.args.get("field_text"))
    return _build_extract_result(merged, found, parts.get_reasoning())


def protocol_to_legacy_selected_mark(data: dict[str, Any]) -> dict[str, Any]:
    """映射"从多个候选中选择一个"的旧结构"""
    if not is_protocol_v1(data):
        return data

    parts = _ProtocolParts.from_data(data)
    if parts.action != "select":
        return data

    selected = parts.args.get("selected_mark_id")
    if selected is None and (item := _extract_item_from_args(parts.args)):
        selected = item.get("mark_id")

    return {"selected_mark_id": selected, "reasoning": parts.get_reasoning()}
