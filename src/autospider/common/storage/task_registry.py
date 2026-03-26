"""全局任务注册表。

以归一化 URL 为主键，记录每次成功执行的任务摘要，
供后续发起同 URL 任务时快速查找历史并复用配置与进度。

当 DB_ENABLED=true 时自动使用 PostgreSQL 后端（通过 TaskRepository），
否则回退到 JSON 文件存储，保持向后兼容。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from autospider.common.config import config
from autospider.common.logger import get_logger

logger = get_logger(__name__)

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

        返回按 updated_at 降序排列的列表（最近的在前）。
        """
        target = normalize_url(url)
        if not target:
            return []

        if self._db_enabled:
            return self._db_find_by_url(target)
        return self._file_find_by_url(target)

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
        ).hexdigest()[:8]

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
