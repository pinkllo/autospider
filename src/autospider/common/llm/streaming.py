"""LLM streaming helpers for gateways that only emit content in stream chunks."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import BaseMessage, message_chunk_to_message


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

    chunks = [chunk async for chunk in llm.astream(messages)]
    return _merge_stream_chunks(chunks)


def invoke_with_stream(llm: Any, messages: Sequence[BaseMessage]) -> Any:
    """Synchronously invoke ChatOpenAI via streaming and merge chunks."""
    if not hasattr(llm, "stream"):
        raise RuntimeError("Configured LLM does not support streaming")

    return _merge_stream_chunks(list(llm.stream(messages)))
