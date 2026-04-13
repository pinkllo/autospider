"""Async bridge for pipeline run persistence helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

from . import run_store

_ResultT = TypeVar("_ResultT")


async def _call_run_store(
    operation: Callable[..., _ResultT],
    /,
    **kwargs: Any,
) -> _ResultT:
    return await asyncio.to_thread(operation, **kwargs)


async def _release_inflight_items_for_resume(execution_id: str) -> int:
    return await _call_run_store(
        run_store._release_inflight_items_for_resume,
        execution_id=execution_id,
    )


async def _persist_run_snapshot(**kwargs: Any) -> None:
    await _call_run_store(run_store._persist_run_snapshot, **kwargs)


async def _claim_persisted_item(**kwargs: Any) -> dict[str, Any]:
    return await _call_run_store(run_store._claim_persisted_item, **kwargs)


async def _commit_persisted_item(**kwargs: Any) -> dict[str, Any]:
    return await _call_run_store(run_store._commit_persisted_item, **kwargs)


async def _fail_persisted_item(**kwargs: Any) -> dict[str, Any]:
    return await _call_run_store(run_store._fail_persisted_item, **kwargs)


async def _ack_persisted_item(**kwargs: Any) -> dict[str, Any]:
    return await _call_run_store(run_store._ack_persisted_item, **kwargs)


async def _release_persisted_claim(**kwargs: Any) -> dict[str, Any]:
    return await _call_run_store(run_store._release_persisted_claim, **kwargs)
