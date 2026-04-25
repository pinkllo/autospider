"""Collector URL publication and urls.txt ownership boundary."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from autospider.platform.observability.logger import get_logger
from autospider.platform.persistence.files.idempotent_io import write_text_if_changed

if TYPE_CHECKING:
    from autospider.contexts.collection.infrastructure.channel.base import URLChannel


logger = get_logger(__name__)


class UrlPublishService:
    """Owns URL backend publication and local urls.txt persistence."""

    def __init__(
        self,
        *,
        output_dir: str = "output",
        url_channel: "URLChannel | None" = None,
    ) -> None:
        self._url_channel = url_channel
        self._urls_file = Path(output_dir) / "urls.txt"
        self._cached_urls: list[str] | None = None
        self._cached_url_set: set[str] = set()

    def backend_persists_urls(self) -> bool:
        if self._url_channel is None:
            return False
        return bool(self._url_channel.persists_published_urls())

    async def load_existing_urls(self) -> list[str]:
        loaded_urls: list[str] = []
        if self._url_channel is not None:
            channel_urls = await self._url_channel.list_existing_urls()
            if channel_urls:
                loaded_urls.extend(channel_urls)
                logger.info(f"从队列后端加载了 {len(channel_urls)} 个历史 URL")
        if not self.backend_persists_urls():
            file_urls = self._load_local_urls()
            if file_urls:
                loaded_urls.extend(file_urls)
                logger.info(f"从本地文件加载了 {len(file_urls)} 个历史 URL")
        return self._dedupe_urls(loaded_urls)

    async def publish(self, url: str) -> None:
        normalized = str(url or "").strip()
        if not normalized:
            return
        if self._url_channel is not None:
            await self._url_channel.publish(normalized)
        if not self.backend_persists_urls():
            self.append_local_urls([normalized])

    def append_local_urls(self, urls: list[str]) -> None:
        if self.backend_persists_urls():
            return
        self._ensure_local_cache()
        new_urls = [url for url in self._dedupe_urls(urls) if url not in self._cached_url_set]
        if not new_urls:
            return
        self._cached_urls.extend(new_urls)
        self._cached_url_set.update(new_urls)
        self._write_local_payload(self._cached_urls)

    def write_snapshot(self, urls: list[str]) -> None:
        if self.backend_persists_urls():
            return
        normalized_urls = self._dedupe_urls(urls)
        self._cached_urls = list(normalized_urls)
        self._cached_url_set = set(normalized_urls)
        self._write_local_payload(normalized_urls)

    def _ensure_local_cache(self) -> None:
        if self._cached_urls is not None:
            return
        existing_urls = self._load_local_urls()
        self._cached_urls = list(existing_urls)
        self._cached_url_set = set(existing_urls)

    def _load_local_urls(self) -> list[str]:
        if not self._urls_file.exists():
            return []
        lines = self._urls_file.read_text(encoding="utf-8").splitlines()
        return self._dedupe_urls(lines)

    def _write_local_payload(self, urls: list[str]) -> None:
        self._urls_file.parent.mkdir(parents=True, exist_ok=True)
        payload = "\n".join(urls)
        if payload:
            payload += "\n"
        write_text_if_changed(self._urls_file, payload)
        logger.debug("[Save] URL 列表已保存到: %s", self._urls_file)

    @staticmethod
    def _dedupe_urls(urls: list[str]) -> list[str]:
        normalized_urls: list[str] = []
        seen: set[str] = set()
        for raw_url in urls:
            normalized = str(raw_url or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            normalized_urls.append(normalized)
        return normalized_urls
