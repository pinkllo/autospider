from __future__ import annotations

DEFAULT_CONTEXT = "platform"
DEFAULT_EVENT = "platform.log"
DEFAULT_LAYER = "application"
EVENT_SEPARATOR = "."
EVENT_FIELDS = (
    "event",
    "layer",
    "context",
    "run_id",
    "trace_id",
)


def event_name(*parts: str) -> str:
    return EVENT_SEPARATOR.join(part.strip() for part in parts if part.strip())
