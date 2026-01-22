"""URL 收集器模块 - 解耦的组件"""

from .models import DetailPageVisit, CommonPattern, URLCollectorResult
from .page_utils import is_at_page_bottom, smart_scroll
from .xpath_extractor import XPathExtractor
from .llm_decision import LLMDecisionMaker
from .url_extractor import URLExtractor
from .navigation_handler import NavigationHandler
from .pagination_handler import PaginationHandler

__all__ = [
    # 数据模型
    "DetailPageVisit",
    "CommonPattern",
    "URLCollectorResult",
    # 工具函数
    "is_at_page_bottom",
    "smart_scroll",
    # 处理器类
    "XPathExtractor",
    "LLMDecisionMaker",
    "URLExtractor",
    "NavigationHandler",
    "PaginationHandler",
]
