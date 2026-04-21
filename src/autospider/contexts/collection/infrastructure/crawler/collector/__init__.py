"""URL 收集器模块 - 解耦的组件"""

from autospider.contexts.collection.application.use_cases.extract_urls import URLExtractor
from autospider.contexts.collection.application.use_cases.navigate import NavigationHandler
from autospider.contexts.collection.application.use_cases.paginate import PaginationHandler
from .models import DetailPageVisit, CommonPattern, URLCollectorResult
from .page_utils import is_at_page_bottom, smart_scroll
from .xpath_extractor import XPathExtractor
from autospider.contexts.collection.infrastructure.adapters.llm_navigator import LLMDecisionMaker

__all__ = [
    "CommonPattern",
    "DetailPageVisit",
    "LLMDecisionMaker",
    "NavigationHandler",
    "PaginationHandler",
    "URLCollectorResult",
    "URLExtractor",
    "XPathExtractor",
    "is_at_page_bottom",
    "smart_scroll",
]
