"""Collection config persistence repository."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from autospider.platform.observability.logger import get_logger
from autospider.platform.persistence.files.idempotent_io import (
    load_json_if_exists,
    write_json_idempotent,
)

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

    def to_storage_record(self) -> dict[str, Any]:
        return {
            "nav_steps": [dict(step) for step in self.nav_steps if isinstance(step, dict)],
            "common_detail_xpath": self.common_detail_xpath,
            "pagination_xpath": self.pagination_xpath,
            "jump_widget_xpath": dict(self.jump_widget_xpath) if self.jump_widget_xpath else None,
            "list_url": self.list_url,
            "anchor_url": self.anchor_url,
            "page_state_signature": self.page_state_signature,
            "variant_label": self.variant_label,
            "task_description": self.task_description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_payload(self) -> dict[str, Any]:
        data = self.to_storage_record()
        return {field: data[field] for field in _CONFIG_PAYLOAD_FIELDS}

    @classmethod
    def from_storage_record(cls, data: Mapping[str, Any]) -> "CollectionConfig":
        return cls(
            nav_steps=[
                dict(step)
                for step in list(data.get("nav_steps") or [])
                if isinstance(step, Mapping)
            ],
            common_detail_xpath=data.get("common_detail_xpath"),
            pagination_xpath=data.get("pagination_xpath"),
            jump_widget_xpath=(
                dict(data.get("jump_widget_xpath"))
                if isinstance(data.get("jump_widget_xpath"), Mapping)
                else None
            ),
            list_url=data.get("list_url", ""),
            anchor_url=data.get("anchor_url", ""),
            page_state_signature=data.get("page_state_signature", ""),
            variant_label=data.get("variant_label", ""),
            task_description=data.get("task_description", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> "CollectionConfig":
        return cls.from_storage_record(data)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CollectionConfig":
        return cls.from_storage_record(data)


class ConfigPersistence:
    def __init__(self, config_dir: str | Path = "output"):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "collection_config.json"

    def save(self, config: CollectionConfig) -> None:
        now = datetime.now().isoformat()
        if not str(config.created_at or "").strip():
            config.created_at = now
        config.updated_at = now
        data = config.to_storage_record()
        persisted = write_json_idempotent(
            self.config_file,
            data,
            identity_keys=(
                "list_url",
                "page_state_signature",
                "anchor_url",
                "variant_label",
                "task_description",
            ),
        )
        normalized = CollectionConfig.from_storage_record(persisted or data)
        config.created_at = normalized.created_at
        config.updated_at = normalized.updated_at
        logger.info("[持久化] 配置已保存到: %s", self.config_file)

    def load(self) -> CollectionConfig | None:
        if not self.config_file.exists():
            logger.info("[持久化] 配置文件不存在: %s", self.config_file)
            return None
        try:
            data = load_json_if_exists(self.config_file)
            if data is None:
                raise ValueError(f"配置文件内容无效: {self.config_file}")
            config = CollectionConfig.from_storage_record(data)
            logger.info("[持久化] 配置已加载: %s", self.config_file)
            return config
        except Exception as exc:
            logger.error("[持久化] 加载配置失败: %s", exc)
            raise RuntimeError(f"failed_to_load_collection_config: {self.config_file}") from exc

    def exists(self) -> bool:
        return self.config_file.exists()


def load_collection_config(
    config_path: str | Path, *, strict: bool = True
) -> CollectionConfig | None:
    path = Path(config_path)
    if not path.exists():
        return None
    data = load_json_if_exists(path)
    if data is None:
        if not strict:
            return None
        raise CollectionConfigLoadError(f"collection config load failed: {path}")
    if not isinstance(data, dict):
        if not strict:
            return None
        raise CollectionConfigLoadError(f"collection config payload must be an object: {path}")
    return CollectionConfig.from_storage_record(data)


def coerce_collection_config(
    value: CollectionConfig | Mapping[str, Any] | None,
) -> CollectionConfig:
    if isinstance(value, CollectionConfig):
        return value
    return CollectionConfig.from_mapping(value or {})
