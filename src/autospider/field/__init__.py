"""字段提取模块

从详情页提取目标字段，支持：
- 导航到目标字段区域
- 字段文本识别和提取
- XPath 生成和验证
- 批量提取和公共模式提取
"""

from .models import (
    FieldDefinition,
    FieldExtractionResult,
    PageExtractionRecord,
    BatchExtractionResult,
    CommonFieldXPath,
)
from .field_extractor import FieldExtractor
from .field_decider import FieldDecider
from .xpath_pattern import FieldXPathExtractor, validate_xpath_pattern
from .batch_field_extractor import BatchFieldExtractor, extract_fields_from_urls
from .batch_xpath_extractor import BatchXPathExtractor, batch_extract_fields_from_urls

__all__ = [
    # 数据模型
    "FieldDefinition",
    "FieldExtractionResult",
    "PageExtractionRecord",
    "BatchExtractionResult",
    "CommonFieldXPath",
    # 提取器
    "FieldExtractor",
    "FieldDecider",
    "FieldXPathExtractor",
    "BatchFieldExtractor",
    "BatchXPathExtractor",
    # 便捷函数
    "extract_fields_from_urls",
    "batch_extract_fields_from_urls",
    "validate_xpath_pattern",
]
