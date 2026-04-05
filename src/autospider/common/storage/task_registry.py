"""全局任务注册表。

以归一化 URL 为主键，记录每次成功执行的任务摘要，
供后续发起同 URL 任务时快速查找历史并复用配置与进度。

当前由 PostgreSQL 作为唯一事实源（通过 TaskRepository）。

缓存策略（Cache-Aside）：
    当 REDIS_ENABLED=true 时，find_by_url 优先查 Redis 缓存，
    未命中才访问 PG 并回写缓存（TTL 可配置）；
    Redis 不可用时自动降级为无缓存模式，不影响主流程。
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from autospider.common.logger import get_logger
from autospider.common.storage.redis_pool import get_sync_client

logger = get_logger(__name__)

# ==================== Redis 缓存辅助 ====================

# 缓存键前缀与默认 TTL
_CACHE_PREFIX = "autospider:task_cache:"
_CACHE_TTL_S = int(os.getenv("TASK_CACHE_TTL", "300"))  # 默认 5 分钟


class _RedisCache:
    """Redis Cache-Aside 辅助类。

    通过全局连接池获取 Redis 客户端，避免各自创建连接。
    任何 Redis 异常都会被静默捕获并记录日志，保证主流程不受影响。
    """

    @property
    def enabled(self) -> bool:
        """仅当 Redis 已启用且连接可用时返回 True。"""
        return self._get_client() is not None

    def _get_client(self) -> Any | None:
        return get_sync_client()

    def get(self, normalized_url: str) -> list[dict[str, Any]] | None:
        """尝试从缓存读取，命中返回列表，未命中或异常返回 None。"""
        client = self._get_client()
        if client is None:
            return None
        try:
            raw = client.get(f"{_CACHE_PREFIX}{normalized_url}")
            if raw is not None:
                logger.debug("[TaskCache] 缓存命中: %s", normalized_url)
                return json.loads(raw)
        except Exception as exc:
            logger.debug("[TaskCache] 读缓存异常（降级）: %s", exc)
        return None

    def set(self, normalized_url: str, data: list[dict[str, Any]], ttl: int | None = None) -> None:
        """回写缓存，带 TTL。

        Args:
            normalized_url: 归一化 URL。
            data: 缓存数据。
            ttl: 自定义 TTL（秒），为 None 时使用默认值。
        """
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
        except Exception as exc:
            logger.debug("[TaskCache] 写缓存异常（忽略）: %s", exc)

    def invalidate(self, normalized_url: str) -> None:
        """写后主动失效缓存，保证一致性。"""
        client = self._get_client()
        if client is None:
            return
        try:
            client.delete(f"{_CACHE_PREFIX}{normalized_url}")
            logger.debug("[TaskCache] 已失效缓存: %s", normalized_url)
        except Exception as exc:
            logger.debug("[TaskCache] 失效缓存异常（忽略）: %s", exc)


# 模块级单例，所有 TaskRegistry 实例共享同一个 Redis 连接
_cache = _RedisCache()

# 需要从 URL 中过滤掉的常见分页参数
_PAGINATION_PARAMS = {"page", "p", "offset", "start", "pagenum", "pn"}


def normalize_url(url: str) -> str:
    """URL 归一化：去除协议、www前缀、尾部斜杠、分页参数和锚点。

    Examples:
        >>> normalize_url("https://www.example.com/news/list?page=2#top")
        'example.com/news/list'
        >>> normalize_url("http://example.com/list/")
        'example.com/list'
    """
    raw = (url or "").strip()
    if not raw:
        return ""

    parsed = urlparse(raw)
    netloc = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/") or "/"

    # 过滤分页参数
    query_params = parse_qs(parsed.query)
    filtered = {
        k: v
        for k, v in query_params.items()
        if k.lower() not in _PAGINATION_PARAMS
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


class TaskRegistry:
    """任务注册表：维护 URL -> 历史任务列表的映射。

    PostgreSQL 是唯一事实源，Redis 仅承担缓存职责。
    """

    # =================================================================
    # 公开 API（统一入口）
    # =================================================================

    def find_by_url(self, url: str) -> list[dict[str, Any]]:
        """按归一化 URL 查找所有历史任务记录。

        使用 Cache-Aside 策略：优先查 Redis 缓存，
        未命中时访问后端存储并回写缓存。

        返回按 updated_at 降序排列的列表（最近的在前）。
        """
        target = normalize_url(url)
        if not target:
            return []

        # 1. 尝试从 Redis 缓存读取
        cached = _cache.get(target)
        if cached is not None:
            return cached

        results = self._db_find_by_url(target)
        _cache.set(target, results, ttl=60 if not results else None)
        return results

    # =================================================================
    # 数据库后端实现
    # =================================================================

    def _db_find_by_url(self, normalized_url: str) -> list[dict[str, Any]]:
        from autospider.common.db.engine import session_scope
        from autospider.common.db.repositories.task_repo import TaskRepository

        with session_scope() as session:
            repo = TaskRepository(session)
            return repo.find_by_url(normalized_url)
