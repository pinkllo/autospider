"""Canonical read-side task run query service."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from autospider.legacy.common.logger import get_logger
from autospider.legacy.common.storage.pipeline_runtime_store import PipelineRuntimeStore
from autospider.legacy.common.storage.redis_pool import get_sync_client

logger = get_logger(__name__)

_CACHE_PREFIX = "autospider:task_cache:"
_CACHE_TTL_S = int(os.getenv("TASK_CACHE_TTL", "300"))
_PAGINATION_PARAMS = {"page", "p", "offset", "start", "pagenum", "pn"}


class _RedisCache:
    """Cache-aside helper for read-side task lookup."""

    @property
    def enabled(self) -> bool:
        return self._get_client() is not None

    def _get_client(self) -> Any | None:
        return get_sync_client()

    def get(self, normalized_url: str) -> list[dict[str, Any]] | None:
        client = self._get_client()
        if client is None:
            return None
        try:
            raw = client.get(f"{_CACHE_PREFIX}{normalized_url}")
            if raw is not None:
                logger.debug("[TaskCache] 缓存命中: %s", normalized_url)
                return json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[TaskCache] 读缓存异常（降级）: %s", exc)
        return None

    def set(self, normalized_url: str, data: list[dict[str, Any]], ttl: int | None = None) -> None:
        client = self._get_client()
        if client is None:
            return
        effective_ttl = ttl if ttl is not None else _CACHE_TTL_S
        try:
            client.setex(
                f"{_CACHE_PREFIX}{normalized_url}",
                effective_ttl,
                json.dumps(data, ensure_ascii=False, default=str),
            )
            logger.debug("[TaskCache] 已回写缓存: %s (TTL=%ds)", normalized_url, effective_ttl)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[TaskCache] 写缓存异常（忽略）: %s", exc)

    def invalidate(self, normalized_url: str) -> None:
        client = self._get_client()
        if client is None:
            return
        try:
            client.delete(f"{_CACHE_PREFIX}{normalized_url}")
            logger.debug("[TaskCache] 已失效缓存: %s", normalized_url)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[TaskCache] 失效缓存异常（忽略）: %s", exc)


_cache = _RedisCache()


def _normalize_query_results(data: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in list(data or []):
        row = dict(item or {})
        row["semantic_signature"] = str(row.get("semantic_signature") or "")
        row["strategy_payload"] = dict(row.get("strategy_payload") or {})
        rows.append(row)
    return rows


def normalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""

    parsed = urlparse(raw)
    netloc = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/") or "/"
    filtered = {
        key: value
        for key, value in parse_qs(parsed.query).items()
        if key.lower() not in _PAGINATION_PARAMS
    }
    query = urlencode(filtered, doseq=True) if filtered else ""
    result = f"{netloc}{path}"
    if query:
        result += f"?{query}"
    return result


def _clean_lookup_value(value: str) -> str:
    return str(value or "").strip()


def build_task_lookup_key(
    url: str,
    *,
    page_state_signature: str = "",
    anchor_url: str = "",
    variant_label: str = "",
) -> dict[str, str]:
    return {
        "normalized_url": normalize_url(url),
        "page_state_signature": _clean_lookup_value(page_state_signature),
        "anchor_url": _clean_lookup_value(anchor_url),
        "variant_label": _clean_lookup_value(variant_label),
    }


def invalidate_task_cache(url: str) -> None:
    normalized = build_task_lookup_key(url)["normalized_url"]
    if normalized:
        _cache.invalidate(normalized)


class TaskRunQueryService:
    """Read-side query service for historical task runs."""

    def __init__(self, runtime_store: PipelineRuntimeStore | None = None) -> None:
        self._runtime_store = runtime_store or PipelineRuntimeStore()

    def find_by_url(self, url: str) -> list[dict[str, Any]]:
        target = build_task_lookup_key(url)["normalized_url"]
        if not target:
            return []

        cached = _cache.get(target)
        if cached is not None:
            return _normalize_query_results(cached)

        results = self._db_find_by_url(target)
        normalized = _normalize_query_results(results)
        _cache.set(target, normalized, ttl=60 if not normalized else None)
        return normalized

    def get_runtime_state(self, execution_id: str) -> dict[str, Any] | None:
        target = str(execution_id or "").strip()
        if not target:
            return None
        return self._runtime_store_get(target)

    def _db_find_by_url(self, normalized_url: str) -> list[dict[str, Any]]:
        from autospider.legacy.common.db.engine import session_scope
        from autospider.legacy.common.db.repositories.task_repo import TaskRepository

        with session_scope() as session:
            repo = TaskRepository(session)
            return repo.find_by_url(normalized_url)

    def get_latest_site_profile(self, url: str) -> dict[str, Any] | None:
        target = normalize_url(url)
        if not target:
            return None
        for snapshot in self._db_list_run_snapshots_by_url(target):
            profile = _extract_site_profile_snapshot(snapshot)
            if profile:
                return profile
        return None

    def _db_list_run_snapshots_by_url(self, normalized_url: str) -> list[dict[str, Any]]:
        from autospider.legacy.common.db.engine import session_scope
        from autospider.legacy.common.db.models import TaskRecord, TaskRun

        with session_scope() as session:
            runs = (
                session.query(TaskRun)
                .join(TaskRecord, TaskRun.task_id == TaskRecord.id)
                .filter(TaskRecord.normalized_url == normalized_url)
                .order_by(TaskRun.started_at.desc(), TaskRun.id.desc())
                .all()
            )
        return [_serialize_run_learning_snapshot(run) for run in runs]


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _serialize_run_learning_snapshot(run: Any) -> dict[str, Any]:
    return {
        "execution_id": str(getattr(run, "execution_id", "") or ""),
        "world_snapshot": _coerce_dict(getattr(run, "world_snapshot", None)),
        "site_profile_snapshot": _coerce_dict(getattr(run, "site_profile_snapshot", None)),
    }


def _extract_site_profile_snapshot(payload: dict[str, Any]) -> dict[str, Any] | None:
    direct = _coerce_dict(payload.get("site_profile_snapshot"))
    if direct:
        return direct

    world_snapshot = _coerce_dict(payload.get("world_snapshot"))
    site_profile = _coerce_dict(world_snapshot.get("site_profile"))
    return site_profile or None


__all__ = [
    "TaskRunQueryService",
    "build_task_lookup_key",
    "invalidate_task_cache",
    "normalize_url",
]
