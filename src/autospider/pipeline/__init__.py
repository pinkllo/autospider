"""Pipeline entrypoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .runner import run_pipeline as run_pipeline

__all__ = ["run_pipeline"]


def __getattr__(name: str) -> Any:
    if name == "run_pipeline":
        from .runner import run_pipeline

        return run_pipeline
    raise AttributeError(f"module 'autospider.pipeline' has no attribute {name!r}")
