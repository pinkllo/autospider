"""全局任务注册表。

以归一化 URL 为主键，记录每次成功执行的任务摘要，
供后续发起同 URL 任务时快速查找历史并复用配置与进度。

当 DB_ENABLED=true 时自动使用 PostgreSQL 后端（通过 TaskRepository），
否则回退到 JSON 文件存储，保持向后兼容。

缓存策略（Cache-Aside）：
    当 REDIS_ENABLED=true 时，find_by_url 优先查 Redis 缓存，
    未命中才访问 PG 并回写缓存（TTL 可配置）；
    register 写入 PG 后主动失效对应缓存键。
    Redis 不可用时自动降级为无缓存模式，不影响主流程。
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from autospider.common.config import config
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


class TaskRegistry:
    """任务注册表：维护 URL -> 历史任务列表的映射。

    当 config.database.enabled=True 时使用 PostgreSQL，
    否则使用 JSON 文件存储（完全向后兼容）。
    """

    def __init__(self, registry_path: str | Path = "output/.task_registry.json"):
        self._path = Path(registry_path)
        self._db_enabled = config.database.enabled

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

        # 2. 缓存未命中 → 查后端存储
        if self._db_enabled:
            results = self._db_find_by_url(target)
        else:
            results = self._file_find_by_url(target)

        # 3. 回写缓存（空结果也缓存 60s，防止缓存穿透）
        _cache.set(target, results, ttl=60 if not results else None)

        return results

    def register(
        self,
        *,
        url: str,
        task_description: str,
        fields: list[str] | None = None,
        execution_id: str = "",
        output_dir: str = "",
        status: str = "completed",
        collected_count: int = 0,
    ) -> None:
        """注册或更新一条任务记录（按 execution_id 做 upsert）。"""
        normalized = normalize_url(url)
        if not normalized:
            return

        if self._db_enabled:
            self._db_register(
                normalized_url=normalized,
                original_url=url,
                task_description=task_description,
                fields=fields,
                execution_id=execution_id,
                output_dir=output_dir,
                status=status,
                collected_count=collected_count,
            )
        else:
            self._file_register(
                normalized_url=normalized,
                original_url=url,
                task_description=task_description,
                fields=fields,
                execution_id=execution_id,
                output_dir=output_dir,
                status=status,
                collected_count=collected_count,
            )

        # 先写后删：PG 写入成功后再失效缓存，缩小并发脏读窗口
        _cache.invalidate(normalized)

    # =================================================================
    # 数据库后端实现
    # =================================================================

    def _db_find_by_url(self, normalized_url: str) -> list[dict[str, Any]]:
        from autospider.common.db.engine import session_scope
        from autospider.common.db.repositories.task_repo import TaskRepository

        with session_scope() as session:
            repo = TaskRepository(session)
            return repo.find_by_url(normalized_url)

    def _db_register(
        self,
        *,
        normalized_url: str,
        original_url: str,
        task_description: str,
        fields: list[str] | None,
        execution_id: str,
        output_dir: str,
        status: str,
        collected_count: int,
    ) -> None:
        from autospider.common.db.engine import session_scope
        from autospider.common.db.repositories.task_repo import TaskRepository

        with session_scope() as session:
            repo = TaskRepository(session)
            repo.register(
                normalized_url=normalized_url,
                original_url=original_url,
                task_description=task_description,
                fields=fields,
                execution_id=execution_id,
                output_dir=output_dir,
                status=status,
                collected_count=collected_count,
            )

    # =================================================================
    # JSON 文件后端实现（原有逻辑，保持向后兼容）
    # =================================================================

    def _file_load(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return list(data) if isinstance(data, list) else []
        except Exception:
            return []

    def _file_save(self, records: list[dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._path.with_suffix(self._path.suffix + ".tmp")
        temp.write_text(
            json.dumps(records, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        temp.replace(self._path)

    def _file_find_by_url(self, target: str) -> list[dict[str, Any]]:
        records = self._file_load()
        matched = [
            r for r in records
            if r.get("normalized_url") == target
        ]
        matched.sort(key=lambda r: r.get("updated_at", ""), reverse=True)
        return matched

    def _file_register(
        self,
        *,
        normalized_url: str,
        original_url: str,
        task_description: str,
        fields: list[str] | None,
        execution_id: str,
        output_dir: str,
        status: str,
        collected_count: int,
    ) -> None:
        now = datetime.now().isoformat()
        registry_id = hashlib.sha1(
            f"{normalized_url}:{task_description}".encode("utf-8")
        ).hexdigest()[:16]

        records = self._file_load()

        # 按 execution_id 查找是否已存在
        existing_idx = None
        if execution_id:
            for idx, r in enumerate(records):
                if r.get("execution_id") == execution_id:
                    existing_idx = idx
                    break

        entry: dict[str, Any] = {
            "registry_id": registry_id,
            "normalized_url": normalized_url,
            "original_url": original_url,
            "task_description": task_description,
            "fields": list(fields or []),
            "execution_id": execution_id,
            "output_dir": output_dir,
            "status": status,
            "collected_count": collected_count,
            "updated_at": now,
        }

        if existing_idx is not None:
            entry["created_at"] = records[existing_idx].get("created_at", now)
            records[existing_idx] = entry
        else:
            entry["created_at"] = now
            # 同 URL + 同 task_description 也做 upsert
            dup_idx = None
            for idx, r in enumerate(records):
                if (
                    r.get("normalized_url") == normalized_url
                    and r.get("task_description") == task_description
                ):
                    dup_idx = idx
                    break

            if dup_idx is not None:
                entry["created_at"] = records[dup_idx].get("created_at", now)
                records[dup_idx] = entry
            else:
                records.append(entry)

        self._file_save(records)
        logger.info(
            "[TaskRegistry] 已注册任务: %s -> %s (采集 %d 条)",
            normalized_url,
            task_description[:40],
            collected_count,
        )
