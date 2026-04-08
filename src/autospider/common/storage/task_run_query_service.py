"""Canonical read-side task run query service."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from autospider.common.logger import get_logger
from autospider.common.storage.redis_pool import get_sync_client

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


def invalidate_task_cache(url: str) -> None:
    normalized = normalize_url(url)
    if normalized:
        _cache.invalidate(normalized)


class TaskRunQueryService:
    """Read-side query service for historical task runs."""

    def find_by_url(self, url: str) -> list[dict[str, Any]]:
        target = normalize_url(url)
        if not target:
            return []

        cached = _cache.get(target)
        if cached is not None:
            return cached

        results = self._db_find_by_url(target)
        _cache.set(target, results, ttl=60 if not results else None)
        return results

    def _db_find_by_url(self, normalized_url: str) -> list[dict[str, Any]]:
        from autospider.common.db.engine import session_scope
        from autospider.common.db.repositories.task_repo import TaskRepository

        with session_scope() as session:
            repo = TaskRepository(session)
            return repo.find_by_url(normalized_url)


__all__ = ["TaskRunQueryService", "invalidate_task_cache", "normalize_url"]
