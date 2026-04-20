"""Pipeline 任务进度追踪器。

将流水线执行进度实时同步到 Redis Hash，
供前端轮询 / WebSocket / CLI 监控读取，避免频繁查询 PostgreSQL。

当 Redis 不可用时自动降级为纯日志模式，不影响主流程。
所有写入方法为 async，通过 asyncio.to_thread 调用同步 Redis，
避免在 asyncio 事件循环中阻塞。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from autospider.legacy.common.logger import get_logger
from autospider.legacy.common.storage.pipeline_runtime_store import PipelineRuntimeStore

logger = get_logger(__name__)

_EXPIRE_S = 3600  # 进度信息保留 1 小时后自动过期
_FINISHED_EXPIRE_S = 600
_CANONICAL_RUNTIME_FIELDS = (
    "stage",
    "resume_mode",
    "thread_id",
    "released_claims",
    "recovered_pending",
    "stream_length",
    "pending_count",
)


def _merge_runtime_state(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    for key, value in dict(incoming or {}).items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _merge_runtime_state(existing, value)
            continue
        merged[key] = value
    return merged


def _extract_canonical_runtime_fields(runtime_state: dict[str, Any]) -> dict[str, Any]:
    canonical = {
        field: value
        for field in _CANONICAL_RUNTIME_FIELDS
        if (value := runtime_state.get(field)) is not None
    }
    queue = runtime_state.get("queue")
    if not isinstance(queue, dict):
        return canonical

    for field in ("stream_length", "pending_count"):
        value = queue.get(field)
        if value is not None and field not in canonical:
            canonical[field] = value
    return canonical


class TaskProgressTracker:
    """任务进度追踪器（读写分离：进度走 Redis，结果走 PG）。

    Args:
        execution_id: 当前执行批次 ID。
    """

    def __init__(
        self,
        execution_id: str,
        *,
        runtime_store: PipelineRuntimeStore | None = None,
    ) -> None:
        self._execution_id = execution_id
        self._completed = 0
        self._failed = 0
        self._total = 0
        self._current_url = ""
        self._last_error = ""
        self._runtime_state: dict[str, Any] = {}
        self._runtime_store = runtime_store or PipelineRuntimeStore()

    def _get_client(self) -> Any | None:
        """保留现有入口，供调用侧检查存储是否可用。"""
        return self._runtime_store._get_client()

    async def set_total(self, total: int) -> None:
        """设置总任务数（通常在 producer 完成后调用）。"""
        self._total = total
        await self._sync()

    async def record_success(self, url: str = "") -> None:
        """记录一条成功。"""
        self._completed += 1
        await self._sync(current_url=url)

    async def record_failure(self, url: str = "", error: str = "") -> None:
        """记录一条失败。"""
        self._failed += 1
        await self._sync(current_url=url, last_error=error)

    async def set_runtime_state(self, runtime_state: dict[str, Any]) -> None:
        """合并并同步 richer runtime state。"""
        self._runtime_state = _merge_runtime_state(self._runtime_state, dict(runtime_state or {}))
        await self._sync()

    async def mark_done(self, final_status: str = "completed") -> None:
        """任务全部完成，更新最终状态并设置短 TTL。"""
        client = self._get_client()
        if client is None:
            return

        finished_at = int(time.time())

        def _do() -> None:
            self._runtime_store.save_runtime_state(
                self._execution_id,
                self._build_state(
                    status=final_status,
                    updated_at=finished_at,
                    finished_at=finished_at,
                ),
                ttl_s=_FINISHED_EXPIRE_S,
            )

        try:
            await asyncio.to_thread(_do)
        except Exception as exc:
            logger.debug("[ProgressTracker] 写入最终状态异常（忽略）: %s", exc)

    async def _sync(self, current_url: str = "", last_error: str = "") -> None:
        """将当前进度同步到 Redis（通过线程池执行同步调用，避免阻塞事件循环）。"""
        client = self._get_client()
        if client is None:
            return

        if current_url:
            self._current_url = current_url[:200]
        if last_error:
            self._last_error = last_error[:500]
        updated_at = int(time.time())

        def _do() -> None:
            self._runtime_store.save_runtime_state(
                self._execution_id,
                self._build_state(updated_at=updated_at),
                ttl_s=_EXPIRE_S,
            )

        try:
            await asyncio.to_thread(_do)
        except Exception as exc:
            logger.debug("[ProgressTracker] 同步进度异常（忽略）: %s", exc)

    @staticmethod
    async def get_progress(execution_id: str) -> dict[str, Any] | None:
        """从 Redis 读取指定任务的进度（供 API 层调用）。

        使用全局连接池而非每次创建新连接。
        """
        runtime_store = PipelineRuntimeStore()

        def _do() -> dict[str, Any] | None:
            return runtime_store.get_runtime_state(execution_id)

        try:
            return await asyncio.to_thread(_do)
        except Exception:
            return None

    def _build_state(
        self,
        *,
        status: str = "running",
        updated_at: int | None = None,
        finished_at: int | None = None,
    ) -> dict[str, Any]:
        state: dict[str, Any] = {
            "execution_id": self._execution_id,
            "status": status,
            "completed": self._completed,
            "failed": self._failed,
            "total": self._total,
            "progress": (
                f"{self._completed + self._failed}/{self._total}"
                if self._total
                else "collecting..."
            ),
        }
        if updated_at is not None:
            state["updated_at"] = updated_at
        if finished_at is not None:
            state["finished_at"] = finished_at
        if self._current_url:
            state["current_url"] = self._current_url
        if self._last_error:
            state["last_error"] = self._last_error
        if self._runtime_state:
            state["runtime_state"] = dict(self._runtime_state)
            state.update(_extract_canonical_runtime_fields(self._runtime_state))
        return state
