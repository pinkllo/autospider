"""Write-side service for learned field XPath results."""

from __future__ import annotations

from autospider.common.db.engine import session_scope
from autospider.common.db.repositories import FieldXPathRepository
from autospider.field.models import PageExtractionRecord

from .field_xpath_query_service import normalize_xpath_domain


class FieldXPathWriteService:
    """Write-side persistence for validated field XPath results."""

    def record(self, url: str, record: PageExtractionRecord, *, success: bool) -> None:
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
