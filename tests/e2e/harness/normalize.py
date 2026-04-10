from __future__ import annotations

from typing import Any, Iterable, Mapping

from tests.e2e.contracts import BUSINESS_FIELDS, SUMMARY_FIELDS


def normalize_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field: record[field]
        for field in BUSINESS_FIELDS
        if field in record
    }


def normalize_records(records: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    normalized = [normalize_record(record) for record in records]
    normalized.sort(key=_record_sort_key)
    return tuple(normalized)


def normalize_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field: summary[field]
        for field in SUMMARY_FIELDS
        if field in summary
    }


def _record_sort_key(record: Mapping[str, Any]) -> tuple[str, str]:
    url = str(record.get("url") or "")
    title = str(record.get("title") or "")
    return (url, title)
