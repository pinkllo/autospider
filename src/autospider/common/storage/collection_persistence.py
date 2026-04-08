"""持久化配置管理。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from autospider.common.logger import get_logger

from ..utils.file_utils import ensure_directory, file_exists, load_json
from .idempotent_io import write_json_idempotent

logger = get_logger(__name__)

_CONFIG_PAYLOAD_FIELDS = (
    "nav_steps",
    "common_detail_xpath",
    "pagination_xpath",
    "jump_widget_xpath",
    "list_url",
    "anchor_url",
    "page_state_signature",
    "variant_label",
    "task_description",
)
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


class CollectionConfigLoadError(RuntimeError):
    """Raised when a persisted collection config cannot be loaded safely."""


@dataclass
class CollectionConfig:
    nav_steps: list[dict[str, Any]] = field(default_factory=list)
    common_detail_xpath: str | None = None
    pagination_xpath: str | None = None
    jump_widget_xpath: dict[str, str] | None = None
    list_url: str = ""
    anchor_url: str = ""
    page_state_signature: str = ""
    variant_label: str = ""
    task_description: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "nav_steps": self.nav_steps,
            "common_detail_xpath": self.common_detail_xpath,
            "pagination_xpath": self.pagination_xpath,
            "jump_widget_xpath": self.jump_widget_xpath,
            "list_url": self.list_url,
            "anchor_url": self.anchor_url,
            "page_state_signature": self.page_state_signature,
            "variant_label": self.variant_label,
            "task_description": self.task_description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_payload(self) -> dict[str, Any]:
        data = self.to_dict()
        return {field: data[field] for field in _CONFIG_PAYLOAD_FIELDS}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CollectionConfig":
        return cls(
            nav_steps=data.get("nav_steps", []),
            common_detail_xpath=data.get("common_detail_xpath"),
            pagination_xpath=data.get("pagination_xpath"),
            jump_widget_xpath=data.get("jump_widget_xpath"),
            list_url=data.get("list_url", ""),
            anchor_url=data.get("anchor_url", ""),
            page_state_signature=data.get("page_state_signature", ""),
            variant_label=data.get("variant_label", ""),
            task_description=data.get("task_description", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


class ConfigPersistence:
    def __init__(self, config_dir: str | Path = "output"):
        self.config_dir = Path(config_dir)
        ensure_directory(self.config_dir)
        self.config_file = self.config_dir / "collection_config.json"

    def save(self, config: CollectionConfig) -> None:
        data = config.to_dict()
        persisted = write_json_idempotent(
            self.config_file,
            data,
            identity_keys=("list_url", "page_state_signature", "anchor_url", "variant_label", "task_description"),
        )
        normalized = CollectionConfig.from_dict(dict(persisted or data))
        config.created_at = normalized.created_at
        config.updated_at = normalized.updated_at
        logger.info("[持久化] 配置已保存到: %s", self.config_file)

    def load(self) -> CollectionConfig | None:
        if not file_exists(self.config_file):
            logger.info("[持久化] 配置文件不存在: %s", self.config_file)
            return None
        try:
            data = load_json(self.config_file)
            if data is None:
                raise ValueError(f"配置文件内容无效: {self.config_file}")
            config = CollectionConfig.from_dict(data)
            logger.info("[持久化] 配置已加载: %s", self.config_file)
            return config
        except Exception as exc:
            logger.error("[持久化] 加载配置失败: %s", exc)
            raise RuntimeError(f"failed_to_load_collection_config: {self.config_file}") from exc

    def exists(self) -> bool:
        return file_exists(self.config_file)


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

    def to_dict(self) -> dict[str, Any]:
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
        data = self.to_dict()
        return {field: data[field] for field in _PROGRESS_PAYLOAD_FIELDS}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CollectionProgress":
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


class ProgressPersistence:
    def __init__(self, output_dir: str | Path = "output"):
        self.output_dir = Path(output_dir)
        ensure_directory(self.output_dir)
        self.progress_file = self.output_dir / "progress.json"

    def save_progress(self, progress: CollectionProgress) -> None:
        progress.last_updated = datetime.now().isoformat()
        data = progress.to_dict()
        persisted = write_json_idempotent(
            self.progress_file,
            data,
            identity_keys=("list_url", "task_description"),
            volatile_keys={"last_updated"},
        )
        normalized = CollectionProgress.from_dict(dict(persisted or data))
        progress.last_updated = normalized.last_updated

    def load_progress(self) -> CollectionProgress | None:
        if not file_exists(self.progress_file):
            return None
        try:
            data = load_json(self.progress_file)
            if data is None:
                raise ValueError(f"进度文件内容无效: {self.progress_file}")
            return CollectionProgress.from_dict(data)
        except Exception as exc:
            logger.error("[进度] 加载进度失败: %s", exc)
            raise RuntimeError(f"failed_to_load_collection_progress: {self.progress_file}") from exc

    def has_checkpoint(self) -> bool:
        return file_exists(self.progress_file)

    def clear(self) -> None:
        if file_exists(self.progress_file):
            self.progress_file.unlink()


def load_collection_config(config_path: str | Path, *, strict: bool = True) -> CollectionConfig | None:
    path = Path(config_path)
    if not path.exists():
        return None
    try:
        data = load_json(path)
    except Exception as exc:
        if not strict:
            return None
        raise CollectionConfigLoadError(f"collection config load failed: {path}") from exc
    if not isinstance(data, dict):
        if not strict:
            return None
        raise CollectionConfigLoadError(f"collection config payload must be an object: {path}")
    return CollectionConfig.from_dict(data)
