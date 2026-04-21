"""LLM client construction helpers."""

from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI

from autospider.platform.config.runtime import config


def build_json_model_kwargs() -> dict[str, Any]:
    """构建统一的 JSON 输出模型参数。"""
    return {
        "response_format": {"type": "json_object"},
    }


def build_llm_extra_body() -> dict[str, Any]:
    """构建统一的扩展请求参数。"""
    return {
        "enable_thinking": config.llm.enable_thinking,
    }


def resolve_runtime_llm_config(
    *,
    prefer_planner: bool,
    use_main_model: bool = False,
) -> dict[str, str | None]:
    """解析运行时 LLM 凭据与模型选择。"""
    if prefer_planner and not use_main_model:
        api_key = config.llm.planner_api_key or config.llm.api_key
        api_base = config.llm.planner_api_base or config.llm.api_base
        model = config.llm.planner_model or config.llm.model
    else:
        api_key = config.llm.api_key
        api_base = config.llm.api_base
        model = config.llm.model
    return {
        "api_key": api_key,
        "api_base": api_base,
        "model": model,
    }


def build_json_chat_openai(
    *,
    api_key: str | None,
    api_base: str | None,
    model: str | None,
    temperature: float,
    max_tokens: int,
) -> ChatOpenAI:
    """构建统一 JSON 响应格式的 ChatOpenAI 客户端。"""
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    return ChatOpenAI(
        api_key=api_key,
        base_url=api_base,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        model_kwargs=build_json_model_kwargs(),
        extra_body=build_llm_extra_body(),
    )


def build_runtime_json_llm(
    *,
    prefer_planner: bool,
    temperature: float,
    max_tokens: int,
    use_main_model: bool = False,
) -> ChatOpenAI:
    """按运行时配置直接构建 ChatOpenAI 客户端。"""
    return build_json_chat_openai(
        **resolve_runtime_llm_config(
            prefer_planner=prefer_planner,
            use_main_model=use_main_model,
        ),
        temperature=temperature,
        max_tokens=max_tokens,
    )
