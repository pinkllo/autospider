from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _cache_key(*, page_state_signature: str, purpose: str, target_text: str = "") -> str:
    return "::".join(
        [
            _clean_text(page_state_signature),
            _clean_text(purpose),
            " ".join(_clean_text(target_text).split()).lower(),
        ]
    )


@dataclass(slots=True)
class VisualDecisionCacheEntry:
    page_state_signature: str = ""
    purpose: str = ""
    target_text: str = ""
    xpath: str = ""
    candidate_text: str = ""
    confidence: float = 0.0
    status: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "page_state_signature": self.page_state_signature,
            "purpose": self.purpose,
            "target_text": self.target_text,
            "xpath": self.xpath,
            "candidate_text": self.candidate_text,
            "confidence": self.confidence,
            "status": self.status,
            "metadata": dict(self.metadata),
        }


class VisualDecisionCache:
    def __init__(self, seed: Mapping[str, Any] | None = None) -> None:
        self._items: dict[str, VisualDecisionCacheEntry] = {}
        raw = dict(seed or {})
        for value in list(raw.get("items") or []):
            if not isinstance(value, Mapping):
                continue
            entry = VisualDecisionCacheEntry(
                page_state_signature=_clean_text(value.get("page_state_signature")),
                purpose=_clean_text(value.get("purpose")),
                target_text=_clean_text(value.get("target_text")),
                xpath=_clean_text(value.get("xpath")),
                candidate_text=_clean_text(value.get("candidate_text")),
                confidence=float(value.get("confidence") or 0.0),
                status=_clean_text(value.get("status")),
                metadata=dict(value.get("metadata") or {}),
            )
            self._items[_cache_key(
                page_state_signature=entry.page_state_signature,
                purpose=entry.purpose,
                target_text=entry.target_text,
            )] = entry

    def get(self, *, page_state_signature: str, purpose: str, target_text: str = "") -> dict[str, Any]:
        entry = self._items.get(
            _cache_key(
                page_state_signature=page_state_signature,
                purpose=purpose,
                target_text=target_text,
            )
        )
        return entry.to_payload() if entry else {}

    def put_success(
        self,
        *,
        page_state_signature: str,
        purpose: str,
        target_text: str = "",
        xpath: str = "",
        candidate_text: str = "",
        confidence: float = 0.0,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        entry = VisualDecisionCacheEntry(
            page_state_signature=_clean_text(page_state_signature),
            purpose=_clean_text(purpose),
            target_text=_clean_text(target_text),
            xpath=_clean_text(xpath),
            candidate_text=_clean_text(candidate_text),
            confidence=float(confidence or 0.0),
            status="success",
            metadata=dict(metadata or {}),
        )
        self._items[_cache_key(
            page_state_signature=entry.page_state_signature,
            purpose=entry.purpose,
            target_text=entry.target_text,
        )] = entry

    def put_reject(
        self,
        *,
        page_state_signature: str,
        purpose: str,
        target_text: str = "",
        reason: str = "",
    ) -> None:
        self.put_success(
            page_state_signature=page_state_signature,
            purpose=purpose,
            target_text=target_text,
            metadata={"reason": _clean_text(reason)},
        )
        self._items[_cache_key(
            page_state_signature=page_state_signature,
            purpose=purpose,
            target_text=target_text,
        )].status = "rejected"

    def to_payload(self) -> dict[str, Any]:
        return {"items": [entry.to_payload() for entry in self._items.values()]}
