"""Crawler 模块 - 采集与规则提取。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .batch.batch_collector import BatchCollector as BatchCollector
    from .batch.batch_collector import batch_collect_urls as batch_collect_urls
    from .explore.config_generator import ConfigGenerator as ConfigGenerator
    from .explore.config_generator import generate_collection_config as generate_collection_config
    from .explore.url_collector import URLCollector as URLCollector
    from .explore.url_collector import collect_detail_urls as collect_detail_urls

__all__ = ["BatchCollector", "batch_collect_urls", "URLCollector", "collect_detail_urls", "ConfigGenerator", "generate_collection_config"]


def __getattr__(name: str) -> Any:
    if name in {"BatchCollector", "batch_collect_urls"}:
        from .batch.batch_collector import BatchCollector, batch_collect_urls

        return BatchCollector if name == "BatchCollector" else batch_collect_urls
    if name in {"URLCollector", "collect_detail_urls"}:
        from .explore.url_collector import URLCollector, collect_detail_urls

        return URLCollector if name == "URLCollector" else collect_detail_urls
    if name in {"ConfigGenerator", "generate_collection_config"}:
        from .explore.config_generator import ConfigGenerator, generate_collection_config

        return ConfigGenerator if name == "ConfigGenerator" else generate_collection_config
    raise AttributeError(f"module 'autospider.crawler' has no attribute {name!r}")
