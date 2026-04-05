"""详情页字段 XPath 仓储。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from autospider.common.db.models import FieldXPath


class FieldXPathRepository:
    """已验证详情页 XPath 的数据库读写入口。"""

    def __init__(self, session: Session):
        self._session = session

    def list_active_xpaths(
        self,
        *,
        domain: str,
        field_name: str,
        min_successes: int,
        limit: int,
    ) -> list[str]:
        if not domain or not field_name:
            return []
        rows = (
            self._session.query(FieldXPath)
            .filter(
                FieldXPath.domain == domain,
                FieldXPath.field_name == field_name,
                FieldXPath.success_count >= min_successes,
            )
            .order_by(
                FieldXPath.success_count.desc(),
                FieldXPath.failure_count.asc(),
                FieldXPath.updated_at.desc(),
            )
            .limit(limit)
            .all()
        )
        return [row.xpath for row in rows]

    def record_result(
        self,
        *,
        domain: str,
        field_name: str,
        xpath: str,
        success: bool,
    ) -> None:
        if not domain or not field_name or not xpath:
            return
        now = datetime.now()
        row = self._find_row(domain=domain, field_name=field_name, xpath=xpath)
        if row is None:
            row = self._create_row(domain=domain, field_name=field_name, xpath=xpath, now=now)
        self._apply_result(row=row, success=success, now=now)
        self._session.flush()

    def _find_row(self, *, domain: str, field_name: str, xpath: str) -> FieldXPath | None:
        return (
            self._session.query(FieldXPath)
            .filter(
                FieldXPath.domain == domain,
                FieldXPath.field_name == field_name,
                FieldXPath.xpath == xpath,
            )
            .first()
        )

    def _create_row(self, *, domain: str, field_name: str, xpath: str, now: datetime) -> FieldXPath:
        row = FieldXPath(
            domain=domain,
            field_name=field_name,
            xpath=xpath,
            created_at=now,
            updated_at=now,
        )
        savepoint = self._session.begin_nested()
        try:
            self._session.add(row)
            self._session.flush()
            savepoint.commit()
            return row
        except IntegrityError:
            savepoint.rollback()
            existing = self._find_row(domain=domain, field_name=field_name, xpath=xpath)
            if existing is None:
                raise
            return existing

    def _apply_result(self, *, row: FieldXPath, success: bool, now: datetime) -> None:
        if success:
            row.success_count += 1
            row.last_success_at = now
        else:
            row.failure_count += 1
            row.last_failure_at = now
        row.updated_at = now
