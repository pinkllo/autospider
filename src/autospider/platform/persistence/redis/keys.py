from __future__ import annotations

from typing import Literal

from autospider.platform.shared_kernel.ids import PlanId, RunId, SkillId, SubTaskId

KEY_PREFIX = "autospider:v1"
EventContext = Literal["planning", "collection", "experience", "chat"]


def plan_key(plan_id: PlanId) -> str:
    return _build_key("plan", plan_id)


def plan_subtasks_key(plan_id: PlanId) -> str:
    return _build_key("plan", plan_id, "subtasks")


def run_key(run_id: RunId) -> str:
    return _build_key("run", run_id)


def run_pages_key(run_id: RunId) -> str:
    return _build_key("run", run_id, "pages")


def run_fields_key(run_id: RunId, subtask_id: SubTaskId) -> str:
    return _build_key("run", run_id, "fields", subtask_id)


def skill_key(skill_id: SkillId) -> str:
    return _build_key("skill", skill_id)


def skill_index_by_host_key(host: str) -> str:
    return _build_key("skill", "index", "by_host", _require_text(host, "host"))


def chat_session_key(session_id: str) -> str:
    return _build_key("chat", "session", _require_text(session_id, "session_id"))


def checkpoint_key(thread_id: str) -> str:
    return _build_key("ckpt", _require_text(thread_id, "thread_id"))


def events_stream_key(context: EventContext) -> str:
    return _build_key("stream", f"events.{context}")


def subtask_queue_key() -> str:
    return _build_key("stream", "queue.subtask")


def subtask_dead_queue_key() -> str:
    return _build_key("stream", "queue.subtask.dead")


def lock_key(resource: str) -> str:
    return _build_key("lock", _require_text(resource, "resource"))


def _build_key(*parts: object) -> str:
    normalized = [KEY_PREFIX]
    for part in parts:
        normalized.append(_require_text(part, "key_part"))
    return ":".join(normalized)


def _require_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text
