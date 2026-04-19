"""Collection domain exports."""

from .field import FieldBinding, FieldDefinition, XPathPattern
from .field.xpath import (
    XPathSegment,
    build_xpath_fallback_chain,
    normalize_xpath,
    strip_indexes,
    xpath_similarity,
    xpath_stability_score,
)
from .model import CollectionRun, PageResult
from .policies import VariantResolver
from .services import append_page_result

__all__ = [
    "CollectionRun",
    "FieldBinding",
    "FieldDefinition",
    "PageResult",
    "VariantResolver",
    "XPathPattern",
    "XPathSegment",
    "append_page_result",
    "build_xpath_fallback_chain",
    "normalize_xpath",
    "strip_indexes",
    "xpath_similarity",
    "xpath_stability_score",
]
