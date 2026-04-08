"""基于文件的 URL 通道实现 (追踪 urls.txt 文件变化)。"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from .base import URLChannel, URLTask


@dataclass
class _FileTaskEntry:
    """文件任务条目，记录URL及文件偏移量等信息"""
    url: str                # 提取到的 URL
    end_offset: int         # 该行在文件中的结束字节偏移量，用于更新游标
    acked: bool = False     # 任务是否已被确认处理完毕


class FileURLChannel(URLChannel):
    """基于文件的被动式 URL 通道。
    
    主要行为是追踪 (tail) 指定的 urls.txt 文件，并维护一个独立的文件游标 (cursor)，
    记录已成功处理行的字节偏移量。它支持断点续传。
    """

    def __init__(
        self,
        urls_file: str | Path,
        cursor_file: str | Path,
        poll_interval: float = 1.0,
    ) -> None:
        """初始化 FileURLChannel
        
        Args:
            urls_file: 存储待爬取 URL 的源文件路径 (如 urls.txt)
            cursor_file: 记录已处理字节偏移量的游标文件路径
            poll_interval: 轮询文件更新的时间间隔（秒），默认 1.0 秒
        """
        self.urls_file = Path(urls_file)
        self.cursor_file = Path(cursor_file)
        self.poll_interval = poll_interval

        self._commit_offset = 0                      # 已确认处理完毕，可持久化的文件偏移量
        self._read_offset = 0                        # 当前从文件中读取到的最新字节偏移量
        self._buffer = b""                           # 行读取时产生的残缺不全的数据缓存区
        self._pending: list[_FileTaskEntry] = []     # 已读取但尚未分发给消费者的任务
        self._inflight: deque[_FileTaskEntry] = deque() # 正在处理中（飞行中）的任务队列，按顺序存入以便顺序 ack
        self._sealed = False

        # 初始化时从本地加载保存的游标
        self._load_cursor()

    async def publish(self, url: str) -> None:
        """发布新的 URL 到通道中。"""
        normalized = str(url or "").strip()
        if not normalized or self._sealed:
            return
        self.urls_file.parent.mkdir(parents=True, exist_ok=True)
        with self.urls_file.open("a", encoding="utf-8") as handle:
            handle.write(f"{normalized}\n")

    async def fetch(self, max_items: int, timeout_s: float | None) -> list[URLTask]:
        """批量获取待处理的 URL 任务。
        
        Args:
            max_items: 单次获取的最大任务数量
            timeout_s: 获取任务的超时时间（秒）。为 None 表示无限等待。
            
        Returns:
            URLTask 任务对象列表
        """
        deadline = None
        if timeout_s is not None and timeout_s > 0:
            deadline = asyncio.get_running_loop().time() + timeout_s

        while True:
            # 如果没有待分发任务，尝试从文件中读取新内容
            if not self._pending:
                self._read_new_lines()
                self._maybe_commit()

            # 如果成功读取到新任务，立即返回切配好的批次
            if self._pending:
                return self._take_pending(max_items)

            # 没有任务且不支持超时机制，休眠后重试
            if timeout_s is None:
                await asyncio.sleep(self.poll_interval)
                continue

            # timeout_s <= 0 表示非阻塞，立刻返回空列表
            if timeout_s <= 0:
                return []

            if self._sealed and not self._pending and not self._inflight:
                return []

            now = asyncio.get_running_loop().time()
            if deadline is not None and now >= deadline:
                return []

            # 休眠指定的轮询间隔后继续下一轮尾部追踪
            await asyncio.sleep(self.poll_interval)

    def _take_pending(self, max_items: int) -> list[URLTask]:
        """从 _pending 队列中截取指定数量的任务分配给正在处理（inflight）的队列，并组装返回结构。"""
        if max_items <= 0:
            max_items = len(self._pending)

        # 截取出本批次数据
        batch = self._pending[:max_items]
        self._pending = self._pending[max_items:]
        self._inflight.extend(batch)

        tasks: list[URLTask] = []
        for entry in batch:
            async def _ack(e: _FileTaskEntry = entry) -> None:
                """成功处理回调：将任务标记为已确认并尝试推进游标记录"""
                e.acked = True
                self._maybe_commit()

            async def _fail(_reason: str, e: _FileTaskEntry = entry) -> None:
                """失败处理回调：失败项重新回到 pending，等待上层重试。"""
                e.acked = False
                try:
                    self._inflight.remove(e)
                except ValueError:
                    return
                self._pending.insert(0, e)

            # 构建最终对外的任务对象
            tasks.append(URLTask(url=entry.url, ack=_ack, fail=_fail))
        return tasks

    def _read_new_lines(self) -> None:
        """增量读取文件末尾新追加的数据行。
        如果文件被截断或者发生大小变化，重置所有的偏移量状态。
        """
        if not self.urls_file.exists():
            return

        try:
            file_size = self.urls_file.stat().st_size
            # 如果文件当前尺寸短于已经提交的偏移量，极有可能文件被清空重建
            # 此时需要做彻底复位（类似 logrotate 的简单处理）
            if file_size < self._commit_offset:
                self._commit_offset = 0
                self._read_offset = 0
                self._buffer = b""
                self._pending = []
                self._inflight.clear()
        except OSError:
            return

        try:
            with self.urls_file.open("rb") as handle:
                handle.seek(self._read_offset)
                chunk = handle.read()
                if not chunk:
                    return
                # 更新目前的文件读取偏移量
                self._read_offset = handle.tell()
        except OSError:
            return

        # 前方遗留的不完整数据加上此次读取的新数据块拼接
        data = self._buffer + chunk
        lines = data.split(b"\n")
        
        # 记录上一轮能够完成解析的位置基准点
        base_offset = self._read_offset - len(data)
        cursor_offset = base_offset

        # 如果末尾没有换行符，说明这行还没写完，需要放入缓冲区下一次继续拼合
        if data and not data.endswith(b"\n"):
            self._buffer = lines.pop()
        else:
            self._buffer = b""

        for raw_line in lines:
            line_len = len(raw_line) + 1  # 包含 \n
            end_offset = cursor_offset + line_len
            cursor_offset = end_offset
            try:
                text = raw_line.decode("utf-8").strip()
            except UnicodeDecodeError:
                # 遇到解码错误的垃圾行直接放入 inflight 并设为 acked，强行推进掉
                self._inflight.append(_FileTaskEntry(url="", end_offset=end_offset, acked=True))
                continue
            
            if not text:
                # 针对空行采取相同丢弃策略
                self._inflight.append(_FileTaskEntry(url="", end_offset=end_offset, acked=True))
                continue
            
            # 正常的 URL 加入待发送队列
            self._pending.append(_FileTaskEntry(url=text, end_offset=end_offset))

    def _maybe_commit(self) -> None:
        """检查是否有连续已经完成 (acked=True) 的任务，若找到则推进文件提交游标，并保存到本地文件。
        
        使用 deque 的原因是要保障游标推进的连续性，不能跨越还没处理完的任务进行不完整的提交。
        """
        advanced = False
        # 只要 inflight 头部任务是 acked 状态，就一直弹出
        while self._inflight and self._inflight[0].acked:
            entry = self._inflight.popleft()
            if entry.end_offset > self._commit_offset:
                self._commit_offset = entry.end_offset
                advanced = True
                
        # 如果游标有了实质性的前进，则保存到磁盘
        if advanced:
            self._save_cursor()

    def _load_cursor(self) -> None:
        """从游标 JSON 文件中读取之前的历史偏移量记录。"""
        if not self.cursor_file.exists():
            self._commit_offset = 0
            self._read_offset = 0
            return

        try:
            data = json.loads(self.cursor_file.read_text(encoding="utf-8"))
            self._commit_offset = int(data.get("offset", 0))
            self._read_offset = self._commit_offset
        except Exception:
            # 发生异常回落至 0
            self._commit_offset = 0
            self._read_offset = 0

    def _save_cursor(self) -> None:
        """将最新的文件游标保存为 JSON 格式本地文件。"""
        payload = {"offset": self._commit_offset}
        try:
            self.cursor_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            return

    async def seal(self) -> None:
        self._sealed = True

    async def is_drained(self) -> bool:
        self._read_new_lines()
        self._maybe_commit()
        return bool(self._sealed and not self._pending and not self._inflight)

    async def list_existing_urls(self) -> list[str]:
        if not self.urls_file.exists():
            return []
        try:
            lines = self.urls_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        return [line.strip() for line in lines if line.strip()]

    def persists_published_urls(self) -> bool:
        return True

    async def close_with_error(self, reason: str) -> None:
        _ = reason
        self._sealed = True
