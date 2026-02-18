"""统一的 LLM 输出解析（action + args + thinking）。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


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


def _normalize_action(value: Any | None) -> str:
    """规范化 action：小写去首尾空白"""
    return str(value).strip().lower() if value else ""


_ACTION_ALIASES = {
    "scroll_down": "scroll",
    "scroll_up": "scroll",
    "press": "retry",
}

_ROOT_ARG_KEYS = (
    "kind",
    "purpose",
    "page_kind",
    "target_text",
    "text",
    "key",
    "url",
    "reasoning",
    "summary",
    "found",
    "mark_id",
    "selected_mark_id",
    "items",
    "input",
    "button",
    "scroll_delta",
    "field_name",
    "field_text",
    "field_value",
    "location_description",
    "confidence",
    "timeout_ms",
    "expectation",
)


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


def coerce_bool(value: Any | None, default: bool | None = None) -> bool | None:
    """对外暴露的布尔值规范化工具。"""
    return _coerce_bool(value, default)


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
        m = self._match(rf'["\']{re.escape(key)}["\']\s*:\s*["\']([^"\']*)["\']')
        if m:
            return m.group(1)
        m = self._match(rf'["\']{re.escape(key)}["\']\s*:\s*([A-Za-z_][\w\-]*)')
        return m.group(1) if m else None

    def integer(self, key: str) -> int | None:
        m = self._match(rf'["\']{re.escape(key)}["\']\s*:\s*"?(\d+)"?')
        try:
            return int(m.group(1)) if m else None
        except ValueError:
            return None

    def boolean(self, key: str) -> bool | None:
        m = self._match(
            rf'["\']{re.escape(key)}["\']\s*:\s*(true|false|"true"|"false"|\'true\'|\'false\'|1|0)'
        )
        return _coerce_bool(m.group(1).strip('"\'')) if m else None

    def floating(self, key: str) -> float | None:
        m = self._match(rf'["\']{re.escape(key)}["\']\s*:\s*(-?\d+(?:\.\d+)?)')
        try:
            return float(m.group(1)) if m else None
        except ValueError:
            return None


def _salvage_json_like_dict(text: str) -> dict[str, Any] | None:
    """尽力从格式错误的文本中抢救关键信息"""
    if not text:
        return None

    cleaned = _strip_code_fences(text)
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
            "purpose",
            "page_kind",
            "target_text",
            "text",
            "key",
            "url",
            "reasoning",
            "field_name",
            "field_text",
            "field_value",
            "location_description",
        ]:
            if (v := ext.string(k)) is not None:
                args[k] = v
        if (v := ext.integer("mark_id")) is not None:
            args["mark_id"] = v
        if (v := ext.integer("selected_mark_id")) is not None:
            args["selected_mark_id"] = v
        if (v := ext.boolean("found")) is not None:
            args["found"] = v
        if (v := ext.floating("confidence")) is not None:
            args["confidence"] = v
        if sd := re.search(r'"scroll_delta"\s*:\s*\[\s*(-?\d+)\s*,\s*(-?\d+)\s*\]', cleaned):
            args["scroll_delta"] = [int(sd.group(1)), int(sd.group(2))]

    # 构建输出
    out: dict[str, Any] = {"action": action, "args": args}
    if thinking := ext.string("thinking"):
        out["thinking"] = thinking
    return out


def _try_parse_json_dict(text: str) -> dict[str, Any] | None:
    """尝试从文本中直接解析 JSON 字典（不做抢救）。"""
    for cand in _iter_json_candidates(text):
        try:
            if isinstance(data := json.loads(_cleanup_json_text(cand)), dict):
                return data
        except Exception:
            continue

    if match := re.search(r"\{[\s\S]*\}", text):
        try:
            if isinstance(data := json.loads(_cleanup_json_text(match.group(0))), dict):
                return data
        except Exception:
            pass

    return None


def parse_json_dict_from_llm(text: str) -> dict[str, Any] | None:
    """从 LLM 文本中提取并解析 JSON 对象"""
    cleaned = _strip_code_fences(text or "")

    # 优先：不改写原文，避免将字符串中的中文引号破坏成非法 JSON
    if parsed := _try_parse_json_dict(cleaned):
        return parsed

    # 兜底1：处理“键名或分隔符用了中文引号”的场景
    normalized = _normalize_quotes(cleaned)
    if normalized != cleaned and (parsed := _try_parse_json_dict(normalized)):
        return parsed

    # 兜底2：抢救式解析（先原文，再归一化文本）
    return _salvage_json_like_dict(cleaned) or (
        _salvage_json_like_dict(normalized) if normalized != cleaned else None
    )


# ---------------------------------------------------------------------------
# 统一结构解析
# ---------------------------------------------------------------------------


def parse_protocol_message(payload: str | dict[str, Any] | None) -> dict[str, Any] | None:
    """解析统一结构：action + args + thinking"""
    if payload is None:
        return None

    data = payload if isinstance(payload, dict) else parse_json_dict_from_llm(payload)
    if not isinstance(data, dict):
        return None

    args = data.get("args") if isinstance(data.get("args"), dict) else {}
    args = dict(args)
    for key in _ROOT_ARG_KEYS:
        if key not in args and data.get(key) is not None:
            args[key] = data.get(key)

    action = _normalize_action(data.get("action"))
    if not action:
        for key in ("next_action", "operation", "decision"):
            action = _normalize_action(data.get(key))
            if action:
                break

    purpose = _normalize_action(args.get("purpose"))
    kind = _normalize_action(args.get("kind"))
    selection_purposes = {
        "detail_links",
        "field_match",
        "pagination_next",
        "next_page",
        "jump_widget",
        "page_jump",
    }

    if not action:
        if args.get("selected_mark_id") is not None:
            action = "select"
        elif isinstance(args.get("items"), list) and purpose in selection_purposes:
            action = "select"
        elif purpose in selection_purposes and (
            args.get("mark_id") is not None
            or args.get("input") is not None
            or args.get("button") is not None
        ):
            action = "select"
        elif kind in {"field", "fields"} or any(
            k in args for k in ("field_name", "field_text", "field_value")
        ):
            action = "extract"
        elif args.get("page_kind") is not None:
            action = "report"
        elif args.get("scroll_delta") is not None:
            action = "scroll"
        elif args.get("url"):
            action = "navigate"
        elif args.get("text") and args.get("mark_id") is not None:
            action = "type"
        elif args.get("mark_id") is not None:
            action = "click"

    action = _ACTION_ALIASES.get(action, action)
    if not action:
        return None

    message: dict[str, Any] = {"action": action, "args": args}

    thinking = data.get("thinking")
    if isinstance(thinking, str) and thinking:
        message["thinking"] = thinking
    elif isinstance(args.get("reasoning"), str) and args.get("reasoning"):
        message["thinking"] = args.get("reasoning")

    return message
