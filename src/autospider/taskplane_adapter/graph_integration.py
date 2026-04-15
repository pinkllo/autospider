"""TaskPlane integration helpers for graph runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..common.config import config
from ..domain.planning import TaskPlan
from ..taskplane.scheduler import TaskScheduler
from ..taskplane.store.base import TaskStore
from ..taskplane.store.dual_store import DualLayerStore
from ..taskplane.store.memory_store import MemoryStore
from ..taskplane.store.pg_store import PgColdStore
from ..taskplane.store.redis_store import RedisHotStore
from .plan_bridge import PlanBridge


@dataclass(slots=True)
class TaskPlaneSession:
    thread_key: str
    envelope_id: str
    scheduler: TaskScheduler


_SESSIONS: dict[str, TaskPlaneSession] = {}


def _resolve_thread_key(thread_id: str, plan_id: str) -> str:
    key = str(thread_id or "").strip() or str(plan_id or "").strip()
    if not key:
        raise ValueError("taskplane_thread_key_required")
    return key


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


async def register_taskplane_plan(
    *,
    thread_id: str,
    plan: TaskPlan,
    request_params: dict[str, Any] | None,
    source_agent: str,
) -> str:
    if not bool(config.taskplane.enabled):
        raise ValueError("taskplane_disabled")
    thread_key = _resolve_thread_key(thread_id, plan.plan_id)
    scheduler = _build_scheduler()
    envelope = PlanBridge.to_envelope(
        plan,
        source_agent=source_agent,
        request_params=dict(request_params or {}),
    )
    await scheduler.submit_envelope(envelope)
    _SESSIONS[thread_key] = TaskPlaneSession(
        thread_key=thread_key,
        envelope_id=envelope.envelope_id,
        scheduler=scheduler,
    )
    return envelope.envelope_id


async def ensure_taskplane_plan_registered(
    *,
    thread_id: str,
    plan: TaskPlan,
    request_params: dict[str, Any] | None,
    source_agent: str,
) -> str:
    thread_key = _resolve_thread_key(thread_id, plan.plan_id)
    if thread_key in _SESSIONS:
        return _SESSIONS[thread_key].envelope_id
    return await register_taskplane_plan(
        thread_id=thread_id,
        plan=plan,
        request_params=request_params,
        source_agent=source_agent,
    )


def get_taskplane_scheduler(*, thread_id: str, plan_id: str) -> TaskScheduler:
    thread_key = _resolve_thread_key(thread_id, plan_id)
    session = _SESSIONS.get(thread_key)
    if session is None:
        raise ValueError(f"taskplane_session_not_found:{thread_key}")
    return session.scheduler


def get_taskplane_envelope_id(*, thread_id: str, plan_id: str) -> str:
    thread_key = _resolve_thread_key(thread_id, plan_id)
    session = _SESSIONS.get(thread_key)
    if session is None:
        return plan_id
    return session.envelope_id
