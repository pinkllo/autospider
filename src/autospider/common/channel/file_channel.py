"""File-based URL channel (tails urls.txt)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .base import URLChannel, URLTask


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

        self._offset = 0
        self._buffer = b""
        self._pending: list[str] = []

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
        return [URLTask(url=url) for url in batch]

    def _read_new_lines(self) -> None:
        if not self.urls_file.exists():
            return

        try:
            file_size = self.urls_file.stat().st_size
            if file_size < self._offset:
                self._offset = 0
                self._buffer = b""
        except OSError:
            return

        try:
            with self.urls_file.open("rb") as handle:
                handle.seek(self._offset)
                chunk = handle.read()
                if not chunk:
                    return
                self._offset = handle.tell()
        except OSError:
            return

        data = self._buffer + chunk
        lines = data.split(b"\n")

        if data and not data.endswith(b"\n"):
            self._buffer = lines.pop()
        else:
            self._buffer = b""

        for raw_line in lines:
            try:
                text = raw_line.decode("utf-8").strip()
            except UnicodeDecodeError:
                continue
            if not text:
                continue
            self._pending.append(text)

        if lines:
            self._save_cursor()

    def _load_cursor(self) -> None:
        if not self.cursor_file.exists():
            self._offset = 0
            return

        try:
            data = json.loads(self.cursor_file.read_text(encoding="utf-8"))
            self._offset = int(data.get("offset", 0))
        except Exception:
            self._offset = 0

    def _save_cursor(self) -> None:
        payload = {"offset": self._offset}
        try:
            self.cursor_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            return
