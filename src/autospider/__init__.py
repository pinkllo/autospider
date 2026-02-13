"""AutoSpider - 纯视觉 SoM 浏览器 Agent"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__version__ = "0.1.0"

if TYPE_CHECKING:
    from .crawler.explore.url_collector import URLCollector as URLCollector
    from .crawler.explore.url_collector import collect_detail_urls as collect_detail_urls
    from .pipeline.runner import run_pipeline as run_pipeline

__all__ = [
    "__version__",
    "URLCollector",
    "collect_detail_urls",
    "run_pipeline",
]


def __getattr__(name: str) -> Any:
    """Lazy exports to avoid importing heavy runtime dependencies at package import time."""
    if name in {"URLCollector", "collect_detail_urls"}:
        from .crawler.explore.url_collector import URLCollector, collect_detail_urls

        return URLCollector if name == "URLCollector" else collect_detail_urls
    if name == "run_pipeline":
        from .pipeline.runner import run_pipeline

        return run_pipeline
    raise AttributeError(f"module 'autospider' has no attribute '{name}'")
