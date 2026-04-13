"""Decision context formatting for LLM prompts.

Filters out runtime-only fields (dispatch_policy, recovery_policy, etc.)
that the LLM cannot interpret, keeping only semantically useful context.
"""

from __future__ import annotations

import json
from typing import Any

# LLM 能理解并使用的字段
_LLM_RELEVANT_KEYS = frozenset({
    "page_model",
    "recent_failures",
})


def format_decision_context(decision_context: dict[str, Any] | None) -> str:
    """格式化 decision_context 供 LLM prompt 使用。

    只保留 page_model 和 recent_failures，过滤掉
    dispatch_policy / recovery_policy / success_criteria 等运行时参数。
    """
    if not decision_context:
        return "无"

    filtered = {
        k: v for k, v in decision_context.items()
        if k in _LLM_RELEVANT_KEYS and v
    }

    if not filtered:
        return "无"

    return json.dumps(filtered, ensure_ascii=False, indent=2, sort_keys=True)
