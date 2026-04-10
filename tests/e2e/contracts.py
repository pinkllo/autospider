from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

BASE_URL_PLACEHOLDER = "{{base_url}}"
BUSINESS_FIELDS = ("url", "title", "publish_date", "budget", "attachment_url")
SUMMARY_FIELDS = ("merged_items", "unique_urls")


def _render_value(value: Any, *, base_url: str) -> Any:
    if isinstance(value, str):
        return value.replace(BASE_URL_PLACEHOLDER, base_url.rstrip("/"))
    if isinstance(value, list):
        return [_render_value(item, base_url=base_url) for item in value]
    if isinstance(value, tuple):
        return tuple(_render_value(item, base_url=base_url) for item in value)
    if isinstance(value, dict):
        return {
            str(key): _render_value(item, base_url=base_url)
            for key, item in value.items()
        }
    return value


@dataclass(frozen=True, slots=True)
class GraphE2ECase:
    case_id: str
    request_text: str
    override_task: dict[str, Any]
    expected_records_file: str
    expected_summary: dict[str, int]
    clarification_answers: tuple[str, ...] = ()

    def materialize_request_text(self, *, base_url: str) -> str:
        payload = _render_value(self.request_text, base_url=base_url)
        if not isinstance(payload, str):
            raise TypeError(f"request_text must be a str: {self.case_id}")
        return payload

    def materialize_override_task(self, *, base_url: str) -> dict[str, Any]:
        payload = _render_value(self.override_task, base_url=base_url)
        if not isinstance(payload, dict):
            raise TypeError(f"override_task must be a dict: {self.case_id}")
        return payload

    def materialize_answers(self, *, base_url: str) -> tuple[str, ...]:
        answers = _render_value(self.clarification_answers, base_url=base_url)
        if not isinstance(answers, tuple):
            raise TypeError(f"clarification_answers must be a tuple: {self.case_id}")
        return answers

    def materialize_expected_summary(self, *, base_url: str) -> dict[str, int]:
        payload = _render_value(self.expected_summary, base_url=base_url)
        if not isinstance(payload, dict):
            raise TypeError(f"expected_summary must be a dict: {self.case_id}")
        return {str(key): int(value) for key, value in payload.items()}


def resolve_golden_path(*, root: Path, case: GraphE2ECase) -> Path:
    return root / "golden" / case.expected_records_file
