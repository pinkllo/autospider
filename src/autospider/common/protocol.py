"""统一的 LLM 输出解析（action + args + thinking）。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
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
    if isinstance(content, Mapping):
        for key in ("text", "content", "output_text", "arguments", "value"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ("content", "message", "output", "result", "response", "data"):
            if key in content:
                nested_text = _extract_text_from_content(content.get(key))
                if nested_text:
                    return nested_text
        for nested in content.values():
            nested_text = _extract_text_from_content(nested)
            if nested_text:
                return nested_text
        return ""
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes, bytearray)):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, Mapping):
                item_type = str(item.get("type") or "").strip().lower()
                if item_type in {"text", "output_text", "message", "json_schema", "tool_result"}:
                    for key in ("text", "content", "output_text", "arguments", "value"):
                        value = item.get(key)
                        if isinstance(value, str) and value.strip():
                            parts.append(value)
                            break
                    continue
                nested_text = _extract_text_from_content(item)
                if nested_text:
                    parts.append(nested_text)
                    continue
            text_attr = getattr(item, "text", None)
            if isinstance(text_attr, str) and text_attr:
                parts.append(text_attr)
                continue
            content_attr = getattr(item, "content", None)
            nested_text = _extract_text_from_content(content_attr)
            if nested_text:
                parts.append(nested_text)
        return "\n".join(part for part in parts if part).strip()
    return str(content)


def _extract_text_candidates(value: Any) -> list[str]:
    """递归收集响应中的候选文本。"""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, Mapping):
        candidates: list[str] = []
        for key in (
            "text",
            "content",
            "output_text",
            "arguments",
            "value",
            "message",
            "output",
            "result",
            "response",
        ):
            if key in value:
                candidates.extend(_extract_text_candidates(value.get(key)))
        if candidates:
            return candidates
        for nested in value.values():
            candidates.extend(_extract_text_candidates(nested))
        return candidates
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        candidates: list[str] = []
        for item in value:
            candidates.extend(_extract_text_candidates(item))
        return candidates
    text_attr = getattr(value, "text", None)
    content_attr = getattr(value, "content", None)
    arguments_attr = getattr(value, "arguments", None)
    candidates: list[str] = []
    for nested in (text_attr, content_attr, arguments_attr):
        candidates.extend(_extract_text_candidates(nested))
    if candidates:
        return candidates
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return _extract_text_candidates(value.model_dump(mode="python"))
        except Exception:
            return []
    return []


def _extract_response_text(payload: Any) -> str:
    """从原始 payload / 响应对象中提取可解析 JSON 的文本。"""
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, Mapping):
        return json.dumps(dict(payload), ensure_ascii=False, default=str)

    text = getattr(payload, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()

    content = getattr(payload, "content", None)
    extracted_content = _extract_text_from_content(content)
    if extracted_content:
        return extracted_content

    for attr in ("additional_kwargs", "response_metadata"):
        extracted = _extract_text_from_content(getattr(payload, attr, None))
        if extracted:
            return extracted

    candidates = _extract_text_candidates(payload)
    return "\n".join(candidate for candidate in candidates if candidate).strip()


_JSON_SIGNAL_KEYS = {
    "action",
    "args",
    "status",
    "intent",
    "next_question",
    "task_description",
    "list_url",
    "fields",
    "selected_indexes",
    "ranked",
}


def _extract_json_dict_from_value(value: Any) -> dict[str, Any] | None:
    """递归从任意响应值中提取最可能的 JSON 对象。"""
    if value is None:
        return None
    if isinstance(value, str):
        return parse_json_dict_from_llm(value)
    if isinstance(value, Mapping):
        value_dict = dict(value)
        if any(key in value_dict for key in _JSON_SIGNAL_KEYS):
            return value_dict
        for preferred_key in (
            "parsed",
            "json",
            "output",
            "result",
            "response",
            "message",
            "data",
            "body",
        ):
            parsed = _extract_json_dict_from_value(value_dict.get(preferred_key))
            if parsed:
                return parsed
        for nested in value_dict.values():
            parsed = _extract_json_dict_from_value(nested)
            if parsed:
                return parsed
        return None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            parsed = _extract_json_dict_from_value(item)
            if parsed:
                return parsed
        return None
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return _extract_json_dict_from_value(value.model_dump(mode="python"))
        except Exception:
            pass
    for attr in ("text", "content", "arguments", "additional_kwargs", "response_metadata"):
        parsed = _extract_json_dict_from_value(getattr(value, attr, None))
        if parsed:
            return parsed
    return None


def _summarize_response_shape(value: Any, *, depth: int = 0, max_depth: int = 5) -> Any:
    """生成可序列化的响应结构摘要，便于定位网关返回格式。"""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if depth >= max_depth:
        return str(type(value).__name__)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {"__type__": type(value).__name__}
        for key in list(value.keys())[:12]:
            result[str(key)] = _summarize_response_shape(value.get(key), depth=depth + 1, max_depth=max_depth)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = list(value)[:6]
        return {
            "__type__": type(value).__name__,
            "length": len(value),
            "items": [_summarize_response_shape(item, depth=depth + 1, max_depth=max_depth) for item in items],
        }
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return {
                "__type__": type(value).__name__,
                "model_dump": _summarize_response_shape(value.model_dump(mode="python"), depth=depth + 1, max_depth=max_depth),
            }
        except Exception:
            pass
    summary = {"__type__": type(value).__name__}
    for attr in ("text", "content", "arguments", "additional_kwargs", "response_metadata"):
        attr_value = getattr(value, attr, None)
        if attr_value is not None:
            summary[attr] = _summarize_response_shape(attr_value, depth=depth + 1, max_depth=max_depth)
    return summary


def summarize_llm_payload(payload: Any) -> dict[str, Any]:
    """返回响应对象结构摘要，供 trace 调试使用。"""
    return {
        "payload_type": type(payload).__name__ if payload is not None else "NoneType",
        "shape": _summarize_response_shape(payload),
    }


def extract_response_text_from_llm_payload(payload: Any) -> str:
    """对外暴露的响应文本提取函数。"""
    return _extract_response_text(payload)


def extract_json_dict_from_llm_payload(payload: Any) -> dict[str, Any] | None:
    """从 LLM 响应对象中尽力提取 JSON 字典。"""
    if payload is None:
        return None
    if isinstance(payload, dict):
        return payload
    if parsed := parse_json_dict_from_llm(_extract_response_text(payload)):
        return parsed
    for attr in ("additional_kwargs", "response_metadata"):
        parsed = _extract_json_dict_from_value(getattr(payload, attr, None))
        if parsed:
            return parsed
    return _extract_json_dict_from_value(getattr(payload, "content", None))


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

    data = payload if isinstance(payload, dict) else extract_json_dict_from_llm_payload(payload)
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
