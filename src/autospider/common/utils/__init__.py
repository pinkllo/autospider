"""通用工具模块"""

from .fuzzy_search import (
    FuzzyTextSearcher,
    TextMatch,
    search_text_in_html,
)

__all__ = [
    "FuzzyTextSearcher",
    "TextMatch",
    "search_text_in_html",
]
