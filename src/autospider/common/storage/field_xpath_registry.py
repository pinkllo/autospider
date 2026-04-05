"""详情页完整 XPath 经验库。"""

from __future__ import annotations

from urllib.parse import urlparse

from autospider.common.db.engine import session_scope
from autospider.common.db.repositories import FieldXPathRepository
from autospider.domain.fields import FieldDefinition
from autospider.field.field_config import field_to_payload
from autospider.field.models import PageExtractionRecord

MIN_ACTIVATION_SUCCESSES = 2
MAX_XPATHS_PER_FIELD = 8


def _normalize_domain(url: str) -> str:
    return urlparse(str(url or "").strip()).netloc.lower().removeprefix("www.").strip()


class FieldXPathRegistry:
    """已验证详情页 XPath 的读取与沉淀入口。"""

    def build_fields_config(self, url: str, fields: list[FieldDefinition]) -> list[dict]:
        domain = _normalize_domain(url)
        configs: list[dict] = []
        if not fields:
            return configs

        with session_scope() as session:
            repo = FieldXPathRepository(session)
            for field in fields:
                payload = field_to_payload(field)
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

    def record(self, url: str, record: PageExtractionRecord, *, success: bool) -> None:
        domain = _normalize_domain(url)
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
