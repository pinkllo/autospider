"""File-based URL channel (tails urls.txt)."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from .base import URLChannel, URLTask


@dataclass
class _FileTaskEntry:
    url: str
    end_offset: int
    acked: bool = False


class FileURLChannel(URLChannel):
    """File channel that tails a urls.txt file and tracks cursor offset."""

    def __init__(
        self,
        urls_file: str | Path,
        cursor_file: str | Path,
        poll_interval: float = 1.0,
    ) -> None:
        self.urls_file = Path(urls_file)
        self.cursor_file = Path(cursor_file)
        self.poll_interval = poll_interval

        self._commit_offset = 0
        self._read_offset = 0
        self._buffer = b""
        self._pending: list[_FileTaskEntry] = []
        self._inflight: deque[_FileTaskEntry] = deque()

        self._load_cursor()

    async def publish(self, url: str) -> None:
        # URLs are already appended by ProgressPersistence in collectors.
        # Keep publish as a no-op to avoid duplicate file writes.
        return None

    async def fetch(self, max_items: int, timeout_s: float | None) -> list[URLTask]:
        deadline = None
        if timeout_s is not None and timeout_s > 0:
            deadline = asyncio.get_running_loop().time() + timeout_s

        while True:
            if not self._pending:
                self._read_new_lines()
                self._maybe_commit()

            if self._pending:
                return self._take_pending(max_items)

            if timeout_s is None:
                await asyncio.sleep(self.poll_interval)
                continue

            if timeout_s <= 0:
                return []

            now = asyncio.get_running_loop().time()
            if deadline is not None and now >= deadline:
                return []

            await asyncio.sleep(self.poll_interval)

    def _take_pending(self, max_items: int) -> list[URLTask]:
        if max_items <= 0:
            max_items = len(self._pending)

        batch = self._pending[:max_items]
        self._pending = self._pending[max_items:]
        self._inflight.extend(batch)

        tasks: list[URLTask] = []
        for entry in batch:
            async def _ack(e: _FileTaskEntry = entry) -> None:
                e.acked = True
                self._maybe_commit()

            async def _fail(_reason: str, e: _FileTaskEntry = entry) -> None:
                # File channel does not support retry; advance cursor on fail to avoid blocking.
                e.acked = True
                self._maybe_commit()

            tasks.append(URLTask(url=entry.url, ack=_ack, fail=_fail))
        return tasks

    def _read_new_lines(self) -> None:
        if not self.urls_file.exists():
            return

        try:
            file_size = self.urls_file.stat().st_size
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
                self._read_offset = handle.tell()
        except OSError:
            return

        data = self._buffer + chunk
        lines = data.split(b"\n")
        base_offset = self._read_offset - len(data)
        cursor_offset = base_offset

        if data and not data.endswith(b"\n"):
            self._buffer = lines.pop()
        else:
            self._buffer = b""

        for raw_line in lines:
            line_len = len(raw_line) + 1  # include newline
            end_offset = cursor_offset + line_len
            cursor_offset = end_offset
            try:
                text = raw_line.decode("utf-8").strip()
            except UnicodeDecodeError:
                self._inflight.append(_FileTaskEntry(url="", end_offset=end_offset, acked=True))
                continue
            if not text:
                self._inflight.append(_FileTaskEntry(url="", end_offset=end_offset, acked=True))
                continue
            self._pending.append(_FileTaskEntry(url=text, end_offset=end_offset))

    def _maybe_commit(self) -> None:
        advanced = False
        while self._inflight and self._inflight[0].acked:
            entry = self._inflight.popleft()
            if entry.end_offset > self._commit_offset:
                self._commit_offset = entry.end_offset
                advanced = True
        if advanced:
            self._save_cursor()

    def _load_cursor(self) -> None:
        if not self.cursor_file.exists():
            self._commit_offset = 0
            self._read_offset = 0
            return

        try:
            data = json.loads(self.cursor_file.read_text(encoding="utf-8"))
            self._commit_offset = int(data.get("offset", 0))
            self._read_offset = self._commit_offset
        except Exception:
            self._commit_offset = 0
            self._read_offset = 0

    def _save_cursor(self) -> None:
        payload = {"offset": self._commit_offset}
        try:
            self.cursor_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            return
