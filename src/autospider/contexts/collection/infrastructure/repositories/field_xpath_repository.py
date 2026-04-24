"""Field XPath read/write repositories for collection extraction."""

from __future__ import annotations

from typing import Protocol
from urllib.parse import urlparse

from autospider.platform.persistence.sql.orm.engine import session_scope
from autospider.platform.persistence.sql.orm.repositories import FieldXPathRepository
from autospider.contexts.collection.domain.fields import FieldDefinition
from autospider.platform.shared_kernel.knowledge_contracts import (
    DETAIL_FIELD_PROFILES_KEY,
    build_detail_template_signature,
    build_field_semantic_signature,
    normalize_profile_metadata,
)

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

    def _list_active_xpaths(
        self,
        *,
        repo: FieldXPathRepository,
        domain: str,
        field_name: str,
    ) -> list[str]:
        return repo.list_active_xpaths(
            domain=domain,
            field_name=field_name,
            min_successes=MIN_ACTIVATION_SUCCESSES,
            limit=MAX_XPATHS_PER_FIELD,
        )

    @staticmethod
    def _resolve_profile_candidate(
        *,
        url: str,
        field: FieldDefinition,
        world_snapshot: dict | None,
    ) -> dict:
        world_model = dict(dict(world_snapshot or {}).get("world_model") or {})
        page_models = dict(world_model.get("page_models") or {})
        template_signature = build_detail_template_signature(
            url=url,
            page_hint=str(field.description or ""),
        )
        field_signature = build_field_semantic_signature(
            field_name=field.name,
            description=field.description,
            data_type=field.data_type,
            extraction_source=str(field.extraction_source or ""),
        )
        for page in page_models.values():
            metadata = normalize_profile_metadata(dict(page).get("metadata"))
            profiles = list(metadata.get(DETAIL_FIELD_PROFILES_KEY) or [])
            for profile in profiles:
                if not isinstance(profile, dict):
                    continue
                if str(profile.get("detail_template_signature") or "") != template_signature:
                    continue
                if str(profile.get("field_signature") or "") != field_signature:
                    continue
                return dict(profile)
        return {}

    def build_fields_config(
        self,
        url: str,
        fields: list[FieldDefinition],
        *,
        world_snapshot: dict | None = None,
    ) -> list[dict]:
        domain = normalize_xpath_domain(url)
        configs: list[dict] = []
        if not fields:
            return configs

        with session_scope() as session:
            repo = FieldXPathRepository(session)
            for field in fields:
                payload = self._field_to_payload(field)
                profile_candidate = self._resolve_profile_candidate(
                    url=url,
                    field=field,
                    world_snapshot=world_snapshot,
                )
                if profile_candidate:
                    payload["xpath"] = str(profile_candidate.get("xpath") or "").strip() or None
                    payload["xpath_fallbacks"] = list(profile_candidate.get("xpath_fallbacks") or [])
                    payload["xpath_validated"] = bool(profile_candidate.get("validated", True))
                    payload["detail_template_signature"] = str(
                        profile_candidate.get("detail_template_signature") or ""
                    )
                    payload["field_signature"] = str(profile_candidate.get("field_signature") or "")
                    configs.append(payload)
                    continue
                xpaths = self._list_active_xpaths(repo=repo, domain=domain, field_name=field.name)
                payload["xpath"] = xpaths[0] if xpaths else None
                payload["xpath_fallbacks"] = xpaths[1:] if len(xpaths) > 1 else []
                payload["detail_template_signature"] = build_detail_template_signature(
                    url=url,
                    page_hint=str(field.description or ""),
                )
                payload["field_signature"] = build_field_semantic_signature(
                    field_name=field.name,
                    description=field.description,
                    data_type=field.data_type,
                    extraction_source=str(field.extraction_source or ""),
                )
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
