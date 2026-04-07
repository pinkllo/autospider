"""Shared helpers for application services."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..common.storage.idempotent_io import write_json_idempotent
from ..domain.fields import FieldDefinition


class CollectionConfigLoadError(RuntimeError):
    """Raised when a persisted collection config exists but cannot be loaded safely."""


def build_field_definitions(raw_fields: list[dict[str, Any]]) -> list[FieldDefinition]:
    fields: list[FieldDefinition] = []
    for raw in raw_fields:
        if not isinstance(raw, dict):
            continue
        fields.append(
            FieldDefinition(
                name=str(raw.get("name") or ""),
                description=str(raw.get("description") or ""),
                required=bool(raw.get("required", True)),
                data_type=str(raw.get("data_type") or "text"),
                example=raw.get("example"),
            )
        )
    return fields


def build_artifact(label: str, path: str | Path) -> dict[str, str]:
    return {"label": label, "path": str(path)}


def collection_config_payload(config_obj: Any) -> dict[str, Any]:
    return {
        "nav_steps": list(getattr(config_obj, "nav_steps", []) or []),
        "common_detail_xpath": getattr(config_obj, "common_detail_xpath", None),
        "pagination_xpath": getattr(config_obj, "pagination_xpath", None),
        "jump_widget_xpath": getattr(config_obj, "jump_widget_xpath", None),
        "list_url": str(getattr(config_obj, "list_url", "") or ""),
        "task_description": str(getattr(config_obj, "task_description", "") or ""),
    }


def load_collection_config_payload(config_path: str | Path, *, strict: bool = True) -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        if not strict:
            return {}
        raise CollectionConfigLoadError(f"collection config load failed: {path}") from exc
    if not isinstance(raw, dict):
        if not strict:
            return {}
        raise CollectionConfigLoadError(f"collection config payload must be an object: {path}")
    return {
        "nav_steps": list(raw.get("nav_steps") or []),
        "common_detail_xpath": raw.get("common_detail_xpath"),
        "pagination_xpath": raw.get("pagination_xpath"),
        "jump_widget_xpath": raw.get("jump_widget_xpath"),
        "list_url": str(raw.get("list_url") or ""),
        "task_description": str(raw.get("task_description") or ""),
    }


def materialize_collection_config(output_dir: str | Path, collection_config: dict[str, Any]) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    config_path = output_path / "collection_config.json"
    write_json_idempotent(
        config_path,
        dict(collection_config or {}),
        identity_keys=("list_url", "task_description"),
    )
    return config_path


def collection_progress_payload(
    *,
    list_url: str,
    task_description: str,
    collected_count: int,
    current_page_num: int = 1,
    status: str = "COMPLETED",
) -> dict[str, Any]:
    return {
        "status": status,
        "pause_reason": None,
        "list_url": list_url,
        "task_description": task_description,
        "current_page_num": current_page_num,
        "collected_count": collected_count,
        "backoff_level": 0,
        "consecutive_success_pages": 0,
    }


def serialize_xpath_result(raw_result: Any) -> dict[str, Any] | None:
    if not isinstance(raw_result, dict):
        return None
    return {
        "fields": list(raw_result.get("fields") or []),
        "records": list(raw_result.get("records") or []),
        "total_urls": int(raw_result.get("total_urls", 0) or 0),
        "success_count": int(raw_result.get("success_count", 0) or 0),
    }
