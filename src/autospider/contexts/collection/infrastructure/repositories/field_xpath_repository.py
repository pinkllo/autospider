"""Field XPath read/write repositories for collection extraction."""

from __future__ import annotations

from typing import Protocol
from urllib.parse import urlparse

from autospider.common.db.engine import session_scope
from autospider.common.db.repositories import FieldXPathRepository
from autospider.domain.fields import FieldDefinition

MIN_ACTIVATION_SUCCESSES = 2
MAX_XPATHS_PER_FIELD = 8


class _ExtractionFieldLike(Protocol):
    xpath: str | None
    field_name: str | None


class ExtractionRecordLike(Protocol):
    fields: list[_ExtractionFieldLike] | None


def normalize_xpath_domain(url: str) -> str:
    return urlparse(str(url or "").strip()).netloc.lower().removeprefix("www.").strip()


class FieldXPathQueryService:
    """Read-side lookup for validated field XPath rules."""

    @staticmethod
    def _field_to_payload(field: FieldDefinition) -> dict:
        return field.model_dump(mode="python")

    def build_fields_config(self, url: str, fields: list[FieldDefinition]) -> list[dict]:
        domain = normalize_xpath_domain(url)
        configs: list[dict] = []
        if not fields:
            return configs

        with session_scope() as session:
            repo = FieldXPathRepository(session)
            for field in fields:
                payload = self._field_to_payload(field)
                xpaths = repo.list_active_xpaths(
                    domain=domain,
                    field_name=field.name,
                    min_successes=MIN_ACTIVATION_SUCCESSES,
                    limit=MAX_XPATHS_PER_FIELD,
                )
                payload["xpath"] = xpaths[0] if xpaths else None
                payload["xpath_fallbacks"] = xpaths[1:] if len(xpaths) > 1 else []
                configs.append(payload)
        return configs


class FieldXPathWriteService:
    """Write-side persistence for validated field XPath results."""

    def record(self, url: str, record: ExtractionRecordLike, *, success: bool) -> None:
        domain = normalize_xpath_domain(url)
        if not domain:
            return
        with session_scope() as session:
            repo = FieldXPathRepository(session)
            for field in list(record.fields or []):
                xpath = str(field.xpath or "").strip()
                field_name = str(field.field_name or "").strip()
                if not xpath or not field_name:
                    continue
                repo.record_result(
                    domain=domain,
                    field_name=field_name,
                    xpath=xpath,
                    success=success,
                )
