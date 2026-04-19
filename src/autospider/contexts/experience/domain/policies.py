from __future__ import annotations

from urllib.parse import urlparse

_ALLOWED_STATUSES = frozenset({"draft", "validated", "unstable", "failed"})


def extract_domain(url: str) -> str:
    parsed = urlparse(str(url or ""))
    host = parsed.netloc or parsed.path.split("/")[0]
    return normalize_host(host)


def normalize_host(host: str) -> str:
    value = str(host or "").strip().lower()
    if not value:
        return ""
    if "@" in value:
        value = value.rsplit("@", 1)[-1]
    if ":" in value and not value.startswith("["):
        value = value.split(":", 1)[0]
    return value.rstrip(".")


def normalize_skill_status(status: str) -> str:
    value = str(status or "").strip().lower()
    if not value:
        raise ValueError("status cannot be empty")
    if value not in _ALLOWED_STATUSES:
        allowed = ", ".join(sorted(_ALLOWED_STATUSES))
        raise ValueError(f"invalid status '{value}', expected one of: {allowed}")
    return value


def clamp_success_rate(value: float) -> float:
    rate = float(value)
    if rate < 0.0:
        return 0.0
    if rate > 1.0:
        return 1.0
    return round(rate, 4)


def compute_success_rate(*, success_count: int, total_count: int) -> float:
    if success_count < 0 or total_count < 0:
        raise ValueError("success_count and total_count must be non-negative")
    if success_count > total_count:
        raise ValueError("success_count cannot exceed total_count")
    if total_count == 0:
        return 0.0
    return clamp_success_rate(success_count / total_count)


def build_success_rate_text(*, success_count: int, total_count: int) -> str:
    if total_count <= 0:
        return ""
    rate = compute_success_rate(success_count=success_count, total_count=total_count)
    return f"{rate * 100:.0f}% ({success_count}/{total_count})"
