"""AutoSpider - 纯视觉 SoM 浏览器 Agent"""

__version__ = "0.1.0"

from .url_collector import URLCollector, collect_detail_urls

__all__ = [
    "__version__",
    "URLCollector",
    "collect_detail_urls",
]
