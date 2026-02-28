"""基于 asyncio.Queue 的内存 URL 通道实现。"""

from __future__ import annotations

import asyncio
from typing import Any

from .base import URLChannel, URLTask


class MemoryURLChannel(URLChannel):
    """基于内存队列的 URL 通道，通常用于单进程爬虫流水线环境。
    
    使用 asyncio.Queue 提供背压和数据传递功能，生命周期限于当前进程内。
    """

    def __init__(self, maxsize: int = 1000) -> None:
        """初始化内存 URL 通道。
        
        Args:
            maxsize: 队列最大容量限制。当通道已满时发布器将会遇到背压而阻塞等待。
        """
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=maxsize)
        self._closed = False  # 标志位：表明通道是否已收到关闭信号

    async def publish(self, url: str) -> None:
        """发布一个新的 URL 任务进入内存队列。
        如果超出 maxsize, 发生阻塞。
        一旦通道关闭，新的推送操作将被忽略。
        """
        if self._closed:
            return
        await self._queue.put(url)

    async def fetch(self, max_items: int, timeout_s: float | None) -> list[URLTask]:
        """批量获取待处理的 URL。
        
        Args:
            max_items: 单次最多获取的任务数量
            timeout_s: 获取任务的超时时间（秒）。为 None 表示无限等待。
            
        Returns:
            获取到的 URLTask 列表
        """
        # 如果通道已关闭且剩余数据均被消费完，立刻返回空列表
        if self._closed and self._queue.empty():
            return []

        items: list[URLTask] = []

        try:
            # 尝试先获取队列中的第一个数据
            if timeout_s is None:
                first = await self._queue.get()
            elif timeout_s <= 0:
                return []
            else:
                first = await asyncio.wait_for(self._queue.get(), timeout=timeout_s)
        except asyncio.TimeoutError:
            return []

        # 获取到的数据如果是 None 表明收到停止的 Poison Pill (毒丸) 信号
        if first is None:
            self._closed = True
            return []

        # 第一个任务有效，加入列表
        items.append(URLTask(url=str(first)))

        # 尝试非阻塞方式尽力抓取其余的数据直到触及 max_items 或队列空
        while len(items) < max_items:
            try:
                next_item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            # 处理队列中堆积的系统停止信号
            if next_item is None:
                self._closed = True
                break
            items.append(URLTask(url=str(next_item)))

        return items

    async def close(self) -> None:
        """关闭内存通道。
        
        通过推入一个 None (毒丸信号) 唤醒可能阻塞在获取队列过程中的消费者。
        """
        if self._closed:
            return
        self._closed = True
        await self._queue.put(None)
