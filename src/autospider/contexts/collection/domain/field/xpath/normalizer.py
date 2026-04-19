from __future__ import annotations

import re

_INDEX_PATTERN = re.compile(r"\[\d+\]")
_SPACE_PATTERN = re.compile(r"\s+")


def normalize_xpath(xpath: str) -> str:
    value = _SPACE_PATTERN.sub("", str(xpath or "").strip())
    if not value:
        return ""
    value = value.replace("/./", "//")
    while "//" in value[2:]:
        value = value.replace("///", "//")
    return value.rstrip("/")


def strip_indexes(xpath: str) -> str:
    return _INDEX_PATTERN.sub("", normalize_xpath(xpath))
