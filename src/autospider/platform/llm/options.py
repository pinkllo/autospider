"""LLM 调用参数工具。"""

from __future__ import annotations


def build_json_model_kwargs() -> dict:
    """构建统一的 JSON 输出模型参数。"""
    return {
        "response_format": {"type": "json_object"},
    }
