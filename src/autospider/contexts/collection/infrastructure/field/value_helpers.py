from __future__ import annotations

import re
from urllib.parse import urlparse


def looks_like_url(value: str) -> bool:
    text = (value or "").strip()
    if text.startswith("/"):
        return True
    try:
        parsed = urlparse(text)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def looks_like_number(value: str) -> bool:
    return bool(re.fullmatch(r"[^\d\-+]*[-+]?\d[\d,\.\s]*[^\d]*", (value or "").strip()))


def looks_like_date(value: str) -> bool:
    text = (value or "").strip()
    patterns = [
        r"\d{4}[-/年]\d{1,2}([-/月]\d{1,2}日?)?",
        r"\d{1,2}[-/]\d{1,2}([-/]\d{2,4})?",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def is_semantically_valid(
    value: str,
    data_type: str | None,
    *,
    max_text_length: int | None = None,
) -> bool:
    text = (value or "").strip()
    if not text:
        return False

    dtype = (data_type or "").strip().lower()
    if dtype == "url":
        return looks_like_url(text)
    if dtype == "number":
        return looks_like_number(text)
    if dtype == "date":
        return looks_like_date(text)
    if max_text_length is not None:
        return len(text) <= max_text_length
    return True
