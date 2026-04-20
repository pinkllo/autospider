from __future__ import annotations

import asyncio

from autospider.platform.shared_kernel.trace import (
    clear_run_context,
    get_run_id,
    get_trace_id,
    set_run_context,
)


async def _capture_context(run_id: str, trace_id: str) -> tuple[str | None, str | None]:
    set_run_context(run_id=run_id, trace_id=trace_id)
    await asyncio.sleep(0)
    return get_run_id(), get_trace_id()


def test_trace_context_can_be_set_and_cleared() -> None:
    clear_run_context()
    set_run_context(run_id="run-100", trace_id="trace-100")

    assert get_run_id() == "run-100"
    assert get_trace_id() == "trace-100"

    clear_run_context()

    assert get_run_id() is None
    assert get_trace_id() is None


def test_trace_context_is_isolated_per_task() -> None:
    clear_run_context()

    async def _run_tasks() -> list[tuple[str | None, str | None]]:
        return await asyncio.gather(
            _capture_context("run-a", "trace-a"),
            _capture_context("run-b", "trace-b"),
        )

    run_ids = asyncio.run(_run_tasks())

    assert run_ids == [("run-a", "trace-a"), ("run-b", "trace-b")]
    assert get_run_id() is None
    assert get_trace_id() is None
