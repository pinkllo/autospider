"""Collection progress persistence repository."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from autospider.legacy.common.logger import get_logger
from autospider.legacy.common.storage.idempotent_io import write_json_idempotent
from autospider.legacy.common.utils.file_utils import ensure_directory, file_exists, load_json

logger = get_logger(__name__)

_PROGRESS_PAYLOAD_FIELDS = (
    "status",
    "pause_reason",
    "list_url",
    "task_description",
    "current_page_num",
    "collected_count",
    "backoff_level",
    "consecutive_success_pages",
)


@dataclass
class CollectionProgress:
    status: str = "RUNNING"
    pause_reason: str | None = None
    list_url: str = ""
    task_description: str = ""
    current_page_num: int = 1
    collected_count: int = 0
    backoff_level: int = 0
    consecutive_success_pages: int = 0
    last_updated: str = ""

    def to_storage_record(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "pause_reason": self.pause_reason,
            "list_url": self.list_url,
            "task_description": self.task_description,
            "current_page_num": self.current_page_num,
            "collected_count": self.collected_count,
            "backoff_level": self.backoff_level,
            "consecutive_success_pages": self.consecutive_success_pages,
            "last_updated": self.last_updated,
        }

    def to_payload(self) -> dict[str, Any]:
        data = self.to_storage_record()
        return {field: data[field] for field in _PROGRESS_PAYLOAD_FIELDS}

    @classmethod
    def from_storage_record(cls, data: Mapping[str, Any]) -> "CollectionProgress":
        return cls(
            status=data.get("status", "RUNNING"),
            pause_reason=data.get("pause_reason"),
            list_url=data.get("list_url", ""),
            task_description=data.get("task_description", ""),
            current_page_num=data.get("current_page_num", 1),
            collected_count=data.get("collected_count", 0),
            backoff_level=data.get("backoff_level", 0),
            consecutive_success_pages=data.get("consecutive_success_pages", 0),
            last_updated=data.get("last_updated", ""),
        )

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> "CollectionProgress":
        return cls.from_storage_record(data)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CollectionProgress":
        return cls.from_storage_record(data)


class ProgressPersistence:
    def __init__(self, output_dir: str | Path = "output"):
        self.output_dir = Path(output_dir)
        ensure_directory(self.output_dir)
        self.progress_file = self.output_dir / "progress.json"

    def save_progress(self, progress: CollectionProgress) -> None:
        progress.last_updated = datetime.now().isoformat()
        data = progress.to_storage_record()
        persisted = write_json_idempotent(
            self.progress_file,
            data,
            identity_keys=("list_url", "task_description"),
            volatile_keys={"last_updated"},
        )
        normalized = CollectionProgress.from_storage_record(persisted or data)
        progress.last_updated = normalized.last_updated

    def load_progress(self) -> CollectionProgress | None:
        if not file_exists(self.progress_file):
            return None
        try:
            data = load_json(self.progress_file)
            if data is None:
                raise ValueError(f"进度文件内容无效: {self.progress_file}")
            return CollectionProgress.from_storage_record(data)
        except Exception as exc:
            logger.error("[进度] 加载进度失败: %s", exc)
            raise RuntimeError(f"failed_to_load_collection_progress: {self.progress_file}") from exc

    def has_checkpoint(self) -> bool:
        return file_exists(self.progress_file)

    def clear(self) -> None:
        if file_exists(self.progress_file):
            self.progress_file.unlink()


def coerce_collection_progress(
    value: CollectionProgress | Mapping[str, Any] | None,
) -> CollectionProgress:
    if isinstance(value, CollectionProgress):
        return value
    return CollectionProgress.from_mapping(value or {})
