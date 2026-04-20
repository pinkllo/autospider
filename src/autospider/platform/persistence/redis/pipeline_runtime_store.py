"""Redis-backed runtime state store for pipeline executions."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from autospider.platform.persistence.redis.pool import get_sync_client

_KEY_PREFIX = "autospider:task_progress:"
_PAYLOAD_FIELD = "payload"
_INT_FIELDS = {
    "completed",
    "failed",
    "total",
    "released_claims",
    "recovered_pending",
    "stream_length",
    "pending_count",
    "updated_at",
    "finished_at",
}
_MIRRORED_FIELDS = {
    "execution_id",
    "status",
    "stage",
    "resume_mode",
    "thread_id",
    "completed",
    "failed",
    "total",
    "progress",
    "current_url",
    "last_error",
    "released_claims",
    "recovered_pending",
    "stream_length",
    "pending_count",
    "updated_at",
    "finished_at",
    "runtime_state",
}


def build_runtime_key(execution_id: str) -> str:
    return f"{_KEY_PREFIX}{str(execution_id or '').strip()}"


def _normalize_legacy_value(field: str, value: Any) -> Any:
    if field in _INT_FIELDS and str(value or "").strip():
        return int(value)
    if field == "runtime_state" and str(value or "").strip():
        return json.loads(value)
    return value


class PipelineRuntimeStore:
    """Small Redis Hash wrapper for pipeline runtime state."""

    def __init__(
        self,
        *,
        client_factory: Callable[[], Any | None] | None = None,
    ) -> None:
        self._client_factory = client_factory or get_sync_client

    def _get_client(self) -> Any | None:
        return self._client_factory()

    def save_runtime_state(
        self,
        execution_id: str,
        state: Mapping[str, Any],
        *,
        ttl_s: int | None = None,
    ) -> None:
        client = self._get_client()
        execution_id = str(execution_id or "").strip()
        if client is None or not execution_id:
            return

        payload = dict(state or {})
        mapping = {_PAYLOAD_FIELD: json.dumps(payload, ensure_ascii=False, default=str)}
        for field in _MIRRORED_FIELDS:
            if field not in payload:
                continue
            value = payload[field]
            if isinstance(value, (dict, list)):
                mapping[field] = json.dumps(value, ensure_ascii=False, default=str)
            else:
                mapping[field] = str(value)

        client.hset(build_runtime_key(execution_id), mapping=mapping)
        if ttl_s is not None:
            client.expire(build_runtime_key(execution_id), ttl_s)

    def get_runtime_state(self, execution_id: str) -> dict[str, Any] | None:
        client = self._get_client()
        execution_id = str(execution_id or "").strip()
        if client is None or not execution_id:
            return None

        raw = client.hgetall(build_runtime_key(execution_id))
        if not raw:
            return None

        payload = str(raw.get(_PAYLOAD_FIELD) or "").strip()
        if payload:
            return dict(json.loads(payload))

        return {
            field: _normalize_legacy_value(field, value)
            for field, value in raw.items()
            if field != _PAYLOAD_FIELD
        }


__all__ = ["PipelineRuntimeStore", "build_runtime_key"]
