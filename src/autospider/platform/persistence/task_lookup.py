"""Shared lookup helpers for persisted task runs."""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse

_PAGINATION_PARAMS = {"page", "p", "offset", "start", "pagenum", "pn"}


def normalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""

    parsed = urlparse(raw)
    netloc = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/") or "/"
    filtered = {
        key: value
        for key, value in parse_qs(parsed.query).items()
        if key.lower() not in _PAGINATION_PARAMS
    }
    query = urlencode(filtered, doseq=True) if filtered else ""
    result = f"{netloc}{path}"
    if query:
        result += f"?{query}"
    return result


def _clean_lookup_value(value: str) -> str:
    return str(value or "").strip()


def build_task_lookup_key(
    url: str,
    *,
    page_state_signature: str = "",
    anchor_url: str = "",
    variant_label: str = "",
) -> dict[str, str]:
    return {
        "normalized_url": normalize_url(url),
        "page_state_signature": _clean_lookup_value(page_state_signature),
        "anchor_url": _clean_lookup_value(anchor_url),
        "variant_label": _clean_lookup_value(variant_label),
    }


__all__ = ["build_task_lookup_key", "normalize_url"]
