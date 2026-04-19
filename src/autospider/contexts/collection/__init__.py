"""Collection context exports."""

from .domain import (
    CollectionRun,
    FieldBinding,
    FieldDefinition,
    PageResult,
    VariantResolver,
    XPathPattern,
    XPathSegment,
    append_page_result,
    build_xpath_fallback_chain,
    normalize_xpath,
    strip_indexes,
    xpath_similarity,
    xpath_stability_score,
)

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
