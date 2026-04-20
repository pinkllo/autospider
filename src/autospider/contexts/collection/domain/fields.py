"""字段领域模型。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any


def _clean_text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass
class FieldDefinition:
    """字段定义。

    该模型属于跨模块共享的领域对象，不应隶属于 field 或 common 基础设施层。
    """

    name: str
    description: str
    required: bool = True
    data_type: str = "text"
    example: str | None = None
    extraction_source: str | None = None
    fixed_value: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "FieldDefinition":
        return cls(
            name=_clean_text(payload.get("name")),
            description=_clean_text(payload.get("description")),
            required=bool(payload.get("required", True)),
            data_type=_clean_text(payload.get("data_type"), "text").lower(),
            example=_optional_text(payload.get("example")),
            extraction_source=_optional_text(payload.get("extraction_source")),
            fixed_value=_optional_text(payload.get("fixed_value")),
        )

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

    def model_dump(self, *, mode: str = "python") -> dict[str, Any]:
        """提供与 Pydantic 模型兼容的最小序列化接口。"""
        _ = mode
        return self.to_payload()


FieldDefinitionMapping = Mapping[str, Any]
FieldDefinitionInput = FieldDefinition | FieldDefinitionMapping


def ensure_field_definition(field: FieldDefinitionInput) -> FieldDefinition:
    if isinstance(field, FieldDefinition):
        return field
    return FieldDefinition.from_mapping(field)


def build_field_definitions(payloads: Sequence[FieldDefinitionInput]) -> list[FieldDefinition]:
    return [ensure_field_definition(payload) for payload in payloads]


def serialize_field_definitions(fields: Sequence[FieldDefinitionInput]) -> list[dict[str, Any]]:
    return [ensure_field_definition(field).to_payload() for field in fields]
