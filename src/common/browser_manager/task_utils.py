"""后台任务工具。

统一创建并回收 asyncio 后台任务，避免出现
"Future exception was never retrieved" 噪音日志。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable

from loguru import logger

_BENIGN_ERROR_MARKERS: tuple[str, ...] = (
    "target page, context or browser has been closed",
    "browser has been closed",
    "context closed",
    "page closed",
    "event loop is closed",
)


def _is_benign_background_error(exc: BaseException) -> bool:
    """判断后台任务异常是否可忽略。"""
    if isinstance(exc, asyncio.CancelledError):
        return True

    message = str(exc).strip().lower()
    return any(marker in message for marker in _BENIGN_ERROR_MARKERS)


def _consume_task_exception(task: asyncio.Task, task_name: str) -> None:
    """消费后台任务异常，防止未读取异常污染日志。"""
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    except Exception as callback_exc:  # noqa: BLE001
        logger.debug(f"[TaskUtils] 读取任务异常失败（忽略） {task_name}: {callback_exc}")
        return

    if exc is None:
        return

    if _is_benign_background_error(exc):
        logger.debug(f"[TaskUtils] 后台任务结束（可忽略） {task_name}: {exc}")
        return

    logger.error(f"[TaskUtils] 后台任务异常 {task_name}: {exc}")


def create_monitored_task(coro: Awaitable, task_name: str) -> asyncio.Task:
    """创建带异常回收的后台任务。"""
    task = asyncio.create_task(coro)

    def _done_callback(done_task: asyncio.Task) -> None:
        _consume_task_exception(done_task, task_name=task_name)

    task.add_done_callback(_done_callback)
    return task

