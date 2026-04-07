"""统一的 LLM 输出解析（action + args + thinking）。"""

from __future__ import annotations

import json
import re
from typing import Any

from .llm_contracts import validate_protocol_message_payload
from .logger import get_logger

logger = get_logger(__name__)

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


def _infer_action_from_args(args: dict[str, Any]) -> str:
    """Infer action from args for compatibility with legacy prompt outputs."""
    if args.get("text") and args.get("target_text"):
        return "type"
    if args.get("scroll_delta") is not None:
        return "scroll"
    if args.get("url"):
        return "navigate"
    if args.get("target_text"):
        return "click"
    return ""


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

    return None


def _extract_text_from_content(content: Any) -> str:
    """从响应 content 中提取文本，兼容 str / block list。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                item_type = str(item.get("type") or "").strip().lower()
                if item_type in {"text", "output_text"} and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                    continue
                if isinstance(item.get("content"), str):
                    parts.append(item["content"])
                    continue
            text_attr = getattr(item, "text", None)
            if isinstance(text_attr, str) and text_attr:
                parts.append(text_attr)
                continue
            content_attr = getattr(item, "content", None)
            if isinstance(content_attr, str) and content_attr:
                parts.append(content_attr)
        return "\n".join(part for part in parts if part).strip()
    return str(content)


def _extract_response_text(payload: Any) -> str:
    """从原始 payload / 响应对象中提取可解析 JSON 的文本。"""
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        return json.dumps(payload, ensure_ascii=False)
    content = getattr(payload, "content", None)
    return _extract_text_from_content(content)


def _extract_reasoning_from_value(value: Any) -> str:
    """递归从响应元数据中提取 thinking/reasoning 文本。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in value:
            extracted = _extract_reasoning_from_value(item)
            if extracted:
                return extracted
        return ""
    if isinstance(value, dict):
        for key in (
            "thinking",
            "reasoning",
            "reasoning_content",
            "reasoning_text",
            "reasoning_summary",
            "thought",
            "thoughts",
        ):
            extracted = _extract_reasoning_from_value(value.get(key))
            if extracted:
                return extracted

        item_type = str(value.get("type") or "").strip().lower()
        if item_type in {"reasoning", "thinking"}:
            for key in ("text", "content", "summary"):
                extracted = _extract_reasoning_from_value(value.get(key))
                if extracted:
                    return extracted

        for nested in value.values():
            extracted = _extract_reasoning_from_value(nested)
            if extracted:
                return extracted
        return ""
    return ""


def _extract_response_thinking(payload: Any) -> str:
    """尽量从响应对象中提取模型思考文本。"""
    if payload is None or isinstance(payload, (str, dict)):
        return ""

    for attr in ("additional_kwargs", "response_metadata"):
        extracted = _extract_reasoning_from_value(getattr(payload, attr, None))
        if extracted:
            return extracted

    content = getattr(payload, "content", None)
    if isinstance(content, list):
        extracted = _extract_reasoning_from_value(content)
        if extracted:
            return extracted

    return ""


# ---------------------------------------------------------------------------
# 统一结构解析
# ---------------------------------------------------------------------------


def parse_protocol_message(payload: Any | None) -> dict[str, Any] | None:
    """解析统一结构：action + args + thinking"""
    if payload is None:
        return None

    data = payload if isinstance(payload, dict) else parse_json_dict_from_llm(_extract_response_text(payload))
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

    if not action:
        action = _infer_action_from_args(args)

    action = _ACTION_ALIASES.get(action, action)
    if not action:
        return None

    validated, errors = validate_protocol_message_payload(
        action=action,
        args=args,
        thinking=_extract_response_thinking(payload),
    )
    if validated is not None:
        return validated

    logger.debug("[Protocol] invalid message action=%s errors=%s payload=%s", action, errors, data)
    return None
