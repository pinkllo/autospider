from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessageChunk, HumanMessage

from autospider.common.llm.streaming import ainvoke_with_stream, invoke_with_stream


class _AsyncFakeLLM:
    def __init__(self, *chunks: AIMessageChunk):
        self.chunks = list(chunks)
        self.messages = []

    async def astream(self, messages):
        self.messages.append(messages)
        for chunk in self.chunks:
            yield chunk


class _SyncFakeLLM:
    def __init__(self, *chunks: AIMessageChunk):
        self.chunks = list(chunks)
        self.messages = []

    def stream(self, messages):
        self.messages.append(messages)
        yield from self.chunks


def test_ainvoke_with_stream_merges_chunked_content():
    llm = _AsyncFakeLLM(
        AIMessageChunk(content=""),
        AIMessageChunk(content='{"status"'),
        AIMessageChunk(content=':"ready"}'),
    )

    message = asyncio.run(ainvoke_with_stream(llm, [HumanMessage(content="hi")]))

    assert message.content == '{"status":"ready"}'
    assert len(llm.messages) == 1


def test_invoke_with_stream_preserves_metadata():
    llm = _SyncFakeLLM(
        AIMessageChunk(content="hello"),
        AIMessageChunk(content="", response_metadata={"finish_reason": "stop"}),
    )

    message = invoke_with_stream(llm, [HumanMessage(content="hi")])

    assert message.content == "hello"
    assert message.response_metadata["finish_reason"] == "stop"
