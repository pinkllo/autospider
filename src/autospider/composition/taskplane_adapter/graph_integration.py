"""TaskPlane integration helpers for the composition graph runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from autospider.contexts.planning.domain import TaskPlan
from autospider.platform.config.runtime import config

from ..taskplane.scheduler import TaskScheduler
from ..taskplane.store.base import TaskStore
from ..taskplane.store.dual_store import DualLayerStore
from ..taskplane.store.memory_store import MemoryStore
from ..taskplane.store.pg_store import PgColdStore
from ..taskplane.store.redis_store import RedisHotStore
from .plan_bridge import PlanBridge
from .result_bridge import ResultBridge
from .subtask_bridge import SubtaskBridge

if TYPE_CHECKING:
    from autospider.contexts.planning.domain.runtime import SubTaskRuntimeState
    from ..taskplane.types import EnvelopeProgress


@dataclass(slots=True)
class TaskPlaneSession:
    thread_key: str
    plan_id: str
    envelope_id: str
    scheduler: TaskScheduler


@dataclass(frozen=True, slots=True)
class TaskPlaneRuntime:
    thread_id: str
    plan_id: str
    envelope_id: str
    scheduler: TaskScheduler

    async def pull_subtasks(self, *, batch_size: int) -> list[Any]:
        tickets = await self.scheduler.pull(batch_size=batch_size)
        return [SubtaskBridge.from_ticket(ticket) for ticket in tickets]

    async def ack_subtask_start(self, subtask_id: str, *, agent_id: str) -> None:
        await self.scheduler.ack_start(subtask_id, agent_id=agent_id)

    async def report_subtask_result(self, result_item: "SubTaskRuntimeState") -> None:
        await self.scheduler.report_result(ResultBridge.to_result(result_item))

    async def get_progress(self) -> "EnvelopeProgress":
        return await self.scheduler.get_envelope_progress(self.envelope_id)

    async def close(self) -> None:
        await close_taskplane_session(thread_id=self.thread_id, plan_id=self.plan_id)


_SESSIONS: dict[str, TaskPlaneSession] = {}


def _resolve_thread_key(thread_id: str, plan_id: str) -> str:
    key = str(thread_id or "").strip() or str(plan_id or "").strip()
    if not key:
        raise ValueError("taskplane_thread_key_required")
    return key


def _resolve_session_key(thread_id: str, plan_id: str) -> str:
    thread_key = _resolve_thread_key(thread_id, plan_id)
    plan_key = _require_non_empty("plan_id", plan_id)
    return f"{thread_key}::{plan_key}"


def _require_non_empty(name: str, value: str) -> str:
    resolved = str(value or "").strip()
    if not resolved:
        raise ValueError(f"taskplane_missing_required_config:{name}")
    return resolved


def _build_store() -> TaskStore:
    store_type = str(config.taskplane.store or "").strip().lower()
    if store_type == "memory":
        return MemoryStore()
    if store_type == "redis":
        redis_url = _require_non_empty("TASKPLANE_REDIS_URL", config.taskplane.redis_url)
        return RedisHotStore(
            redis_url=redis_url,
            namespace=str(config.taskplane.redis_namespace or "taskplane"),
        )
    if store_type == "dual":
        redis_url = _require_non_empty("TASKPLANE_REDIS_URL", config.taskplane.redis_url)
        database_url = _require_non_empty("TASKPLANE_DATABASE_URL", config.taskplane.database_url)
        return DualLayerStore(
            hot_store=RedisHotStore(
                redis_url=redis_url,
                namespace=str(config.taskplane.redis_namespace or "taskplane"),
            ),
            cold_store=PgColdStore(database_url=database_url),
        )
    raise ValueError(f"unsupported_taskplane_store:{store_type or 'missing'}")


def _build_scheduler() -> TaskScheduler:
    return TaskScheduler(store=_build_store())


def _cache_session(
    *,
    thread_id: str,
    plan_id: str,
    envelope_id: str,
    scheduler: TaskScheduler,
) -> TaskPlaneSession:
    thread_key = _resolve_thread_key(thread_id, plan_id)
    session_key = _resolve_session_key(thread_id, plan_id)
    session = TaskPlaneSession(
        thread_key=thread_key,
        plan_id=_require_non_empty("plan_id", plan_id),
        envelope_id=_require_non_empty("envelope_id", envelope_id),
        scheduler=scheduler,
    )
    _SESSIONS[session_key] = session
    return session


def _active_session(session_key: str) -> TaskPlaneSession | None:
    session = _SESSIONS.get(session_key)
    if session is None:
        return None
    if session.scheduler.is_closed:
        _SESSIONS.pop(session_key, None)
        return None
    return session


def _matching_session(session_key: str, envelope_id: str) -> TaskPlaneSession | None:
    session = _active_session(session_key)
    if session is None or session.envelope_id != envelope_id:
        return None
    return session


def _runtime_from_session(*, thread_id: str, plan_id: str, session: TaskPlaneSession) -> TaskPlaneRuntime:
    return TaskPlaneRuntime(
        thread_id=_resolve_thread_key(thread_id, plan_id),
        plan_id=session.plan_id,
        envelope_id=session.envelope_id,
        scheduler=session.scheduler,
    )


async def _restore_taskplane_session(*, thread_id: str, plan_id: str) -> TaskPlaneSession | None:
    session_key = _resolve_session_key(thread_id, plan_id)
    envelope_id = _require_non_empty("envelope_id", plan_id)
    session = _matching_session(session_key, envelope_id)
    if session is not None:
        return session
    scheduler = _build_scheduler()
    envelope = await scheduler.get_envelope(envelope_id)
    if envelope is None:
        await scheduler.aclose()
        return None
    return _cache_session(
        thread_id=thread_id,
        plan_id=plan_id,
        envelope_id=envelope.envelope_id,
        scheduler=scheduler,
    )


async def _register_taskplane_session(
    *,
    thread_id: str,
    plan: TaskPlan,
    request_params: dict[str, Any] | None,
    source_agent: str,
) -> TaskPlaneSession:
    if not bool(config.taskplane.enabled):
        raise ValueError("taskplane_disabled")
    session = await _restore_taskplane_session(thread_id=thread_id, plan_id=plan.plan_id)
    if session is not None:
        return session
    scheduler = _build_scheduler()
    envelope = PlanBridge.to_envelope(
        plan,
        source_agent=source_agent,
        request_params=dict(request_params or {}),
    )
    try:
        await scheduler.submit_envelope(envelope)
    except Exception:
        await scheduler.aclose()
        raise
    return _cache_session(
        thread_id=thread_id,
        plan_id=plan.plan_id,
        envelope_id=envelope.envelope_id,
        scheduler=scheduler,
    )


async def register_taskplane_plan(
    *,
    thread_id: str,
    plan: TaskPlan,
    request_params: dict[str, Any] | None,
    source_agent: str,
) -> str:
    session = await _register_taskplane_session(
        thread_id=thread_id,
        plan=plan,
        request_params=request_params,
        source_agent=source_agent,
    )
    return session.envelope_id


async def ensure_taskplane_plan_registered(
    *,
    thread_id: str,
    plan: TaskPlan,
    request_params: dict[str, Any] | None,
    source_agent: str,
) -> str:
    runtime = await ensure_taskplane_runtime(
        thread_id=thread_id,
        plan=plan,
        request_params=request_params,
        source_agent=source_agent,
    )
    return runtime.envelope_id


async def ensure_taskplane_runtime(
    *,
    thread_id: str,
    plan: TaskPlan,
    request_params: dict[str, Any] | None,
    source_agent: str,
) -> TaskPlaneRuntime:
    session = await _restore_taskplane_session(thread_id=thread_id, plan_id=plan.plan_id)
    if session is None:
        session = await _register_taskplane_session(
            thread_id=thread_id,
            plan=plan,
            request_params=request_params,
            source_agent=source_agent,
        )
    return _runtime_from_session(thread_id=thread_id, plan_id=plan.plan_id, session=session)


def get_taskplane_scheduler(*, thread_id: str, plan_id: str) -> TaskScheduler:
    session_key = _resolve_session_key(thread_id, plan_id)
    session = _active_session(session_key)
    if session is None:
        raise ValueError(f"taskplane_session_not_found:{session_key}")
    return session.scheduler


async def close_taskplane_session(*, thread_id: str, plan_id: str) -> None:
    session_key = _resolve_session_key(thread_id, plan_id)
    session = _SESSIONS.pop(session_key, None)
    if session is None or session.scheduler.is_closed:
        return
    if any(existing.scheduler is session.scheduler for existing in _SESSIONS.values()):
        return
    await session.scheduler.aclose()


async def close_all_taskplane_sessions() -> None:
    sessions = list(_SESSIONS.values())
    _SESSIONS.clear()
    closed_ids: set[int] = set()
    for session in sessions:
        scheduler = session.scheduler
        scheduler_id = id(scheduler)
        if scheduler.is_closed or scheduler_id in closed_ids:
            continue
        closed_ids.add(scheduler_id)
        await scheduler.aclose()
