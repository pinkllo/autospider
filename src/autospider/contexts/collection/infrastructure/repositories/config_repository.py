"""Collection config persistence repository."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from autospider.platform.shared_kernel.knowledge_contracts import (
    JumpWidgetProfile,
    ListPageProfile,
    coerce_list_page_profile,
)
from autospider.platform.observability.logger import get_logger
from autospider.platform.persistence.files.idempotent_io import (
    load_json_if_exists,
    write_json_idempotent,
)

logger = get_logger(__name__)

_CONFIG_PAYLOAD_FIELDS = (
    "profile_key",
    "nav_steps",
    "common_detail_xpath",
    "pagination_xpath",
    "jump_widget_xpath",
    "list_url",
    "anchor_url",
    "page_state_signature",
    "variant_label",
    "task_description",
    "profile_validation_status",
    "profile_reject_reason",
)


class CollectionConfigLoadError(RuntimeError):
    """Raised when a persisted collection config cannot be loaded safely."""


@dataclass
class CollectionConfig:
    profile_key: str = ""
    nav_steps: list[dict[str, Any]] = field(default_factory=list)
    common_detail_xpath: str | None = None
    pagination_xpath: str | None = None
    jump_widget_xpath: dict[str, str] | None = None
    list_url: str = ""
    anchor_url: str = ""
    page_state_signature: str = ""
    variant_label: str = ""
    task_description: str = ""
    profile_validation_status: str = ""
    profile_reject_reason: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_list_page_profile(self) -> ListPageProfile:
        return ListPageProfile(
            profile_key=self.profile_key,
            list_url=self.list_url,
            anchor_url=self.anchor_url,
            page_state_signature=self.page_state_signature,
            variant_label=self.variant_label,
            task_description=self.task_description,
            nav_steps=tuple(
                dict(step) for step in self.nav_steps if isinstance(step, Mapping)
            ),
            common_detail_xpath=str(self.common_detail_xpath or ""),
            pagination_xpath=str(self.pagination_xpath or ""),
            jump_widget_xpath=JumpWidgetProfile.from_mapping(self.jump_widget_xpath),
        )

    def to_storage_record(self) -> dict[str, Any]:
        profile = self.to_list_page_profile()
        return {
            "profile_key": profile.profile_key,
            "nav_steps": [dict(step) for step in profile.nav_steps],
            "common_detail_xpath": profile.common_detail_xpath or None,
            "pagination_xpath": profile.pagination_xpath or None,
            "jump_widget_xpath": profile.jump_widget_xpath.to_payload(),
            "list_url": profile.list_url,
            "anchor_url": profile.anchor_url,
            "page_state_signature": profile.page_state_signature,
            "variant_label": profile.variant_label,
            "task_description": profile.task_description,
            "profile_validation_status": self.profile_validation_status,
            "profile_reject_reason": self.profile_reject_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_payload(self) -> dict[str, Any]:
        data = self.to_storage_record()
        return {field: data[field] for field in _CONFIG_PAYLOAD_FIELDS}

    @classmethod
    def from_storage_record(cls, data: Mapping[str, Any]) -> "CollectionConfig":
        profile = coerce_list_page_profile(data)
        return cls(
            profile_key=profile.profile_key,
            nav_steps=[dict(step) for step in profile.nav_steps],
            common_detail_xpath=profile.common_detail_xpath or None,
            pagination_xpath=profile.pagination_xpath or None,
            jump_widget_xpath=profile.jump_widget_xpath.to_payload(),
            list_url=profile.list_url,
            anchor_url=profile.anchor_url,
            page_state_signature=profile.page_state_signature,
            variant_label=profile.variant_label,
            task_description=profile.task_description,
            profile_validation_status=str(data.get("profile_validation_status") or ""),
            profile_reject_reason=str(data.get("profile_reject_reason") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> "CollectionConfig":
        return cls.from_storage_record(data)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CollectionConfig":
        return cls.from_storage_record(data)

    @classmethod
    def from_list_page_profile(cls, profile: ListPageProfile | Mapping[str, Any]) -> "CollectionConfig":
        normalized = coerce_list_page_profile(profile)
        return cls(
            profile_key=normalized.profile_key,
            nav_steps=[dict(step) for step in normalized.nav_steps],
            common_detail_xpath=normalized.common_detail_xpath or None,
            pagination_xpath=normalized.pagination_xpath or None,
            jump_widget_xpath=normalized.jump_widget_xpath.to_payload(),
            list_url=normalized.list_url,
            anchor_url=normalized.anchor_url,
            page_state_signature=normalized.page_state_signature,
            variant_label=normalized.variant_label,
            task_description=normalized.task_description,
            profile_validation_status=str(
                getattr(profile, "profile_validation_status", "")
                if not isinstance(profile, Mapping)
                else profile.get("profile_validation_status") or ""
            ),
            profile_reject_reason=str(
                getattr(profile, "profile_reject_reason", "")
                if not isinstance(profile, Mapping)
                else profile.get("profile_reject_reason") or ""
            ),
        )


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
