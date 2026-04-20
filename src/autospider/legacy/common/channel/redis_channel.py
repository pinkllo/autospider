"""基于 Redis 的 URL 通道实现。"""

from __future__ import annotations

import asyncio
import socket
import os
from collections import deque

from autospider.legacy.common.logger import get_logger

from .base import ChannelRuntimeEvent, ChannelRuntimeObserver, URLChannel, URLTask
from ..storage.redis_manager import RedisQueueManager
from ..config import config

logger = get_logger(__name__)


class RedisURLChannel(URLChannel):
    """基于 Redis Stream 底层的 URL 通道包装类。

    能够依赖 Redis 实现强大的分布式任务分配、多消费者协同和消息失败重试与死信机制。
    提供了连接保障、任务获取、恢复死信消息的自动后台轮询循环机制。
    """

    def __init__(
        self,
        manager: RedisQueueManager,
        consumer_name: str | None = None,
        block_ms: int = 5000,
        max_retries: int = 3,
        runtime_observer: ChannelRuntimeObserver | None = None,
    ) -> None:
        """初始化基于 Redis 的通道。

        Args:
            manager: RedisQueueManager，提供底层的 Stream 操作
            consumer_name: 消费者名称，用于在消费者组内标识自己，如果不传入会自动根据主机名和进程ID生成唯一名称
            block_ms: XREADGROUP 阻塞读取的超时毫秒数
            max_retries: 允许失败的最大重试次数，超越此次数直接归入死信流
        """
        self.manager = manager
        # 默认使用 主机名-进程号 作为消费者唯一名字，确保分布式下区分彼此
        self.consumer_name = consumer_name or f"pipeline-{socket.gethostname()}-{os.getpid()}"
        self.block_ms = block_ms
        self.max_retries = max_retries
        self._connected = False  # Redis 是否连接成功的标记位
        self._recover_task: asyncio.Task | None = (
            None  # 用于自动检查并接管 stale/超时未处理的遗留信息的后台定时任务
        )
        self._retry_buffer: deque[tuple[str, str, dict]] = deque()
        self._background_error: RuntimeError | None = None
        self._sealed = False
        self._error_reason = ""
        self._runtime_observer = runtime_observer

    def _raise_background_error(self) -> None:
        if self._background_error is not None:
            raise self._background_error

    def _observe_runtime(
        self,
        *,
        operation: str,
        item_count: int = 0,
        reason: str = "",
        drained: bool | None = None,
        **metadata: object,
    ) -> None:
        if self._runtime_observer is None:
            return
        self._runtime_observer(
            ChannelRuntimeEvent(
                operation=operation,
                item_count=max(0, int(item_count)),
                reason=str(reason or ""),
                drained=drained,
                metadata={key: value for key, value in metadata.items()},
            )
        )

    async def _recover_pending_once(self) -> None:
        """执行一次遗留未 ack (Pending) 消息的恢复逻辑。

        扫描消费者组内处理超时的旧消息（可能来自于挂断的消费者端），改变它们的拥有权从而继续重新被当前消费者执行消费。
        受全局配置 config.redis.auto_recover 和 config.redis.task_timeout_ms 控制。
        """
        self._raise_background_error()
        if not self._connected or not config.redis.auto_recover:
            return
        recovered = await self.manager.recover_stale_tasks(
            consumer_name=self.consumer_name,
            max_idle_ms=config.redis.task_timeout_ms,
            count=config.redis.fetch_batch_size,
        )
        if recovered:
            self._retry_buffer.extend(recovered)
        self._observe_runtime(
            operation="recover",
            item_count=len(recovered),
            retry_buffer_size=len(self._retry_buffer),
            consumer_name=self.consumer_name,
        )

    def _start_recover_loop(self) -> None:
        """启动后台死信及僵尸任务恢复轮询循环。"""
        if self._recover_task is not None or not config.redis.auto_recover:
            return

        interval_s = max(1, int(config.redis.task_timeout_ms / 1000))

        async def _loop() -> None:
            while True:
                try:
                    await asyncio.sleep(interval_s)
                    await self._recover_pending_once()
                except asyncio.CancelledError:
                    break  # 当关闭通道时，任务被主动取消退出循环
                except Exception as exc:  # noqa: BLE001
                    logger.error("[RedisURLChannel] 后台恢复失败: %s", exc)
                    self._background_error = RuntimeError(f"redis_recovery_failed: {exc}")
                    break

        # 创建后台常驻任务
        self._recover_task = asyncio.create_task(_loop())

    async def _ensure_connected(self) -> None:
        """确保已经成功连接到 Redis。如果是首次连接，则初始化相关自动恢复机制。"""
        self._raise_background_error()
        if self._connected:
            return

        # 建立底层 Redis 链接客户端
        client = await self.manager.connect()
        if client is None:
            raise RuntimeError("redis_channel_unavailable")
        self._connected = True

        if self._connected and config.redis.auto_recover:
            # 刚连上时优先强行恢复一波之前可能遗留的超时数据
            await self._recover_pending_once()
            # 启动定期检测
            self._start_recover_loop()

    async def publish(self, url: str) -> None:
        """向 Redis 流推送单条新派发的 URL 任务。

        Args:
            url: 被处理的目标 URL 字符串
        """
        self._raise_background_error()
        if self._sealed:
            raise RuntimeError("channel_sealed")
        await self._ensure_connected()
        # 使用 manager 投递任务到流的队尾
        await self.manager.push_task(url)

    async def fetch(self, max_items: int, timeout_s: float | None) -> list[URLTask]:
        """批量获取 Redis 中的待抓取任务，包装为标准 URLTask 返回给管道引擎处理。

        Args:
            max_items: 欲批量拉取的消息最大条数
            timeout_s: 指定获取时的阻塞等待时长（秒）。如果是 None，则长阻塞或使用默认 block_ms。

        Returns:
            URLTask 对象序列
        """
        self._raise_background_error()
        await self._ensure_connected()

        # 获取超时参数换算适配为阻塞毫秒数
        block_ms = self.block_ms
        if timeout_s is not None:
            if timeout_s <= 0:
                block_ms = 0
            else:
                block_ms = int(timeout_s * 1000)

        buffered: list[tuple[str, str, dict]] = []
        while self._retry_buffer and len(buffered) < max_items:
            buffered.append(self._retry_buffer.popleft())
        if buffered:
            tasks = buffered
            source = "retry_buffer"
        else:
            # 底层借用 redis-py `xreadgroup` 实现消费者抢占读取
            tasks = await self.manager.fetch_task(
                consumer_name=self.consumer_name,
                block_ms=block_ms,
                count=max_items,
            )
            source = "redis"

        self._observe_runtime(
            operation="fetch",
            item_count=len(tasks),
            requested_items=max_items,
            block_ms=block_ms,
            source=source,
            retry_buffer_size=len(self._retry_buffer),
        )

        wrapped: list[URLTask] = []
        # 对 Redis Stream 读取出来的结果集按条目进行拆包和重封装
        for stream_id, data_id, data in tasks:
            url = data.get("url", "")

            # 定制任务生命周期确认回调：向 redis 汇报 ack（确认），表明该任务成功完成
            async def _ack(sid: str = stream_id, did: str = data_id) -> None:
                await self.manager.ack_task(sid, did)

            # 定制任务生命周期失败回调：通知 redis 以增加失败计数器，到达最大重试次数将放入死信处理
            async def _fail(
                reason: str,
                sid: str = stream_id,
                did: str = data_id,
                task_data: dict = data,
            ) -> None:
                result = await self.manager.fail_task_state(
                    sid,
                    did,
                    reason,
                    max_retries=self.max_retries,
                )
                if result == "retry":
                    self._retry_buffer.append((sid, did, dict(task_data)))

            async def _release(
                reason: str,
                sid: str = stream_id,
                did: str = data_id,
            ) -> None:
                released = await self.manager.release_task(sid, did, reason)
                if not released:
                    raise RuntimeError(f"redis_release_failed:{did}")
                self._observe_runtime(
                    operation="release",
                    item_count=1,
                    reason=reason,
                    stream_id=sid,
                    data_id=did,
                    consumer_name=self.consumer_name,
                )

            # 组装返回最终给业务侧消费者的任务对象
            wrapped.append(URLTask(url=url, ack=_ack, fail=_fail, release=_release))

        return wrapped

    async def list_existing_urls(self) -> list[str]:
        self._raise_background_error()
        await self._ensure_connected()
        items = await self.manager.get_all_items()
        return [
            str(data.get("url") or "").strip()
            for data in items.values()
            if str(data.get("url") or "").strip()
        ]

    async def close(self) -> None:
        """安全干净地关闭通道及底层 Redis 连接。"""
        if self._recover_task is not None:
            task = self._recover_task
            self._recover_task = None
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        # 关闭底层 Redis 连接
        await self.manager.close()

    async def seal(self) -> None:
        self._sealed = True

    async def is_drained(self) -> bool:
        if not self._sealed:
            return False
        self._raise_background_error()
        await self._ensure_connected()
        stream_length = await self.manager.get_stream_length()
        drained = stream_length <= 0 and not self._retry_buffer
        self._observe_runtime(
            operation="is_drained",
            drained=drained,
            stream_length=stream_length,
            retry_buffer_size=len(self._retry_buffer),
            sealed=self._sealed,
        )
        return drained

    async def close_with_error(self, reason: str) -> None:
        self._error_reason = str(reason or "")
        self._sealed = True
