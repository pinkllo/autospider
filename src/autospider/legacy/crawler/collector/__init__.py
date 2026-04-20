"""URL 收集器模块 - 解耦的组件"""

from .models import DetailPageVisit, CommonPattern, URLCollectorResult
from .page_utils import is_at_page_bottom, smart_scroll
from .xpath_extractor import XPathExtractor
from ....contexts.collection.infrastructure.adapters.llm_navigator import LLMDecisionMaker
from .url_extractor import URLExtractor
from .navigation_handler import NavigationHandler
from .pagination_handler import PaginationHandler

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
