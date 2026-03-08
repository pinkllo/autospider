from __future__ import annotations

from typing import Any

from playwright.async_api import Page


class BrowserInterventionRequired(RuntimeError):
    """Raised when browser automation needs human intervention via graph interrupt."""

    def __init__(self, payload: dict[str, Any]):
        self.payload = dict(payload)
        message = str(payload.get("message") or "browser_intervention_required")
        super().__init__(message)


def get_page_guard(page: Page) -> Any | None:
    try:
        return getattr(page, "_page_guard", None)
    except Exception:
        return None


def interrupts_enabled(page: Page) -> bool:
    guard = get_page_guard(page)
    return bool(guard and str(getattr(guard, "intervention_mode", "blocking")) == "interrupt")


def build_interrupt_payload(
    page: Page,
    *,
    intervention_type: str,
    handler_name: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    guard = get_page_guard(page)
    payload = {
        "type": "browser_intervention",
        "intervention_type": intervention_type,
        "handler_name": handler_name,
        "message": message,
        "url": str(getattr(page, "url", "") or ""),
        "thread_id": str(getattr(guard, "thread_id", "") or ""),
    }
    if details:
        payload["details"] = dict(details)
    return payload
