from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


@dataclass(frozen=True, slots=True)
class FieldDefinition:
    name: str
    description: str
    required: bool = True
    data_type: str = "text"
    example: str | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "FieldDefinition":
        return cls(
            name=_text(payload.get("name")),
            description=_text(payload.get("description")),
            required=bool(payload.get("required", True)),
            data_type=_text(payload.get("data_type")) or "text",
            example=_text(payload.get("example")) or None,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "required": self.required,
            "data_type": self.data_type,
            "example": self.example,
        }


@dataclass(frozen=True, slots=True)
class XPathPattern:
    xpath: str
    fallback_xpaths: tuple[str, ...] = ()
    support_count: int = 0
    confidence: float = 0.0

    def to_payload(self) -> dict[str, Any]:
        return {
            "xpath": self.xpath,
            "fallback_xpaths": list(self.fallback_xpaths),
            "support_count": self.support_count,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class FieldBinding:
    field: FieldDefinition
    pattern: XPathPattern | None = None
    source: str = "unknown"
    metadata: dict[str, str] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "field": self.field.to_payload(),
            "pattern": None if self.pattern is None else self.pattern.to_payload(),
            "source": self.source,
            "metadata": dict(self.metadata),
        }
