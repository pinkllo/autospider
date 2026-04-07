"""Shared helpers for application services."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..common.storage.idempotent_io import write_json_idempotent
from ..common.storage.persistence import CollectionConfig
from ..domain.fields import FieldDefinition


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


def materialize_collection_config(output_dir: str | Path, collection_config: dict[str, Any]) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    config_path = output_path / "collection_config.json"
    normalized = CollectionConfig.from_dict(dict(collection_config or {})).to_dict()
    write_json_idempotent(
        config_path,
        normalized,
        identity_keys=("list_url", "task_description"),
    )
    return config_path


def serialize_xpath_result(raw_result: Any) -> dict[str, Any] | None:
    if not isinstance(raw_result, dict):
        return None
    return {
        "fields": list(raw_result.get("fields") or []),
        "records": list(raw_result.get("records") or []),
        "total_urls": int(raw_result.get("total_urls", 0) or 0),
        "success_count": int(raw_result.get("success_count", 0) or 0),
    }
