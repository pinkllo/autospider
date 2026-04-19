from .generator import build_xpath_fallback_chain
from .matcher import xpath_similarity
from .normalizer import normalize_xpath, strip_indexes
from .patterns import XPathSegment
from .scorer import xpath_stability_score

__all__ = [
    "XPathSegment",
    "build_xpath_fallback_chain",
    "normalize_xpath",
    "strip_indexes",
    "xpath_similarity",
    "xpath_stability_score",
]
