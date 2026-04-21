"""Crawler exploration (rule extraction) phase."""

from autospider.contexts.collection.application.use_cases.collect_urls import (
    URLCollector,
    collect_detail_urls,
)
from .config_generator import ConfigGenerator, generate_collection_config

__all__ = [
    "ConfigGenerator",
    "URLCollector",
    "collect_detail_urls",
    "generate_collection_config",
]
