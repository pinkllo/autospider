"""LLM streaming helpers for gateways that only emit content in stream chunks."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import BaseMessage, message_chunk_to_message
from autospider.platform.observability.logger import get_logger

logger = get_logger(__name__)


def _merge_stream_chunks(chunks: Sequence[Any]) -> Any:
    if not chunks:
        raise RuntimeError("LLM stream returned no chunks")

    merged = chunks[0]
    for chunk in chunks[1:]:
        merged += chunk
    return message_chunk_to_message(merged)


async def ainvoke_with_stream(llm: Any, messages: Sequence[BaseMessage]) -> Any:
    """Invoke ChatOpenAI via streaming and merge chunks into a single message."""
    if not hasattr(llm, "astream"):
        raise RuntimeError("Configured LLM does not support async streaming")

    chunks: list[Any] = []
    try:
        async for chunk in llm.astream(messages):
            chunks.append(chunk)
    except AssertionError as exc:
        if not hasattr(llm, "ainvoke"):
            raise RuntimeError("LLM stream failed before completion and ainvoke is unavailable") from exc
        logger.warning(
            "[LLM] astream transport failed before completion; retrying with ainvoke: %s",
            exc,
        )
        return await llm.ainvoke(messages)
    if not chunks:
        if not hasattr(llm, "ainvoke"):
            raise RuntimeError("LLM stream returned no chunks")
        logger.warning("[LLM] astream returned no chunks; retrying with ainvoke")
        return await llm.ainvoke(messages)
    return _merge_stream_chunks(chunks)


def invoke_with_stream(llm: Any, messages: Sequence[BaseMessage]) -> Any:
    """Synchronously invoke ChatOpenAI via streaming and merge chunks."""
    if not hasattr(llm, "stream"):
        raise RuntimeError("Configured LLM does not support streaming")

    try:
        chunks = list(llm.stream(messages))
    except AssertionError as exc:
        if not hasattr(llm, "invoke"):
            raise RuntimeError("LLM stream failed before completion and invoke is unavailable") from exc
        logger.warning("[LLM] stream transport failed before completion; retrying with invoke: %s", exc)
        return llm.invoke(messages)
    if not chunks:
        if not hasattr(llm, "invoke"):
            raise RuntimeError("LLM stream returned no chunks")
        logger.warning("[LLM] stream returned no chunks; retrying with invoke")
        return llm.invoke(messages)
    return _merge_stream_chunks(chunks)
