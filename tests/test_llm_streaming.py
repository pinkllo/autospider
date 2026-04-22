from __future__ import annotations

import pytest

from autospider.platform.llm.streaming import ainvoke_with_stream, invoke_with_stream


class _AsyncFallbackLLM:
    def __init__(self, *, error: Exception | None = None, chunks: list[object] | None = None) -> None:
        self._error = error
        self._chunks = list(chunks or [])
        self.ainvoke_calls = 0

    async def astream(self, _messages):
        if self._error is not None:
            raise self._error
        for chunk in self._chunks:
            yield chunk

    async def ainvoke(self, _messages):
        self.ainvoke_calls += 1
        return {"mode": "ainvoke"}


class _SyncFallbackLLM:
    def __init__(self, *, error: Exception | None = None, chunks: list[object] | None = None) -> None:
        self._error = error
        self._chunks = list(chunks or [])
        self.invoke_calls = 0

    def stream(self, _messages):
        if self._error is not None:
            raise self._error
        return iter(self._chunks)

    def invoke(self, _messages):
        self.invoke_calls += 1
        return {"mode": "invoke"}


@pytest.mark.asyncio
async def test_ainvoke_with_stream_falls_back_to_ainvoke_on_assertion_error() -> None:
    llm = _AsyncFallbackLLM(error=AssertionError("empty completion"))

    result = await ainvoke_with_stream(llm, [])

    assert result == {"mode": "ainvoke"}
    assert llm.ainvoke_calls == 1


@pytest.mark.asyncio
async def test_ainvoke_with_stream_falls_back_to_ainvoke_on_empty_stream() -> None:
    llm = _AsyncFallbackLLM()

    result = await ainvoke_with_stream(llm, [])

    assert result == {"mode": "ainvoke"}
    assert llm.ainvoke_calls == 1


def test_invoke_with_stream_falls_back_to_invoke_on_assertion_error() -> None:
    llm = _SyncFallbackLLM(error=AssertionError("empty completion"))

    result = invoke_with_stream(llm, [])

    assert result == {"mode": "invoke"}
    assert llm.invoke_calls == 1


def test_invoke_with_stream_falls_back_to_invoke_on_empty_stream() -> None:
    llm = _SyncFallbackLLM()

    result = invoke_with_stream(llm, [])

    assert result == {"mode": "invoke"}
    assert llm.invoke_calls == 1
