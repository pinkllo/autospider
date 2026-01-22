"""字段提取数据模型定义"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class FieldDefinition:
    """字段定义

    用于描述要提取的目标字段。
    """

    name: str  # 字段名称（如 "title", "price", "date"）
    description: str  # 字段描述（供 LLM 理解，如 "招标项目的标题"）
    required: bool = True  # 是否必填
    data_type: str = "text"  # 数据类型: text, number, date, url
    example: str | None = None  # 示例值（帮助 LLM 理解格式）


@dataclass
class FieldExtractionResult:
    """单个字段的提取结果"""

    field_name: str  # 字段名称
    value: str | None = None  # 提取到的值
    xpath: str | None = None  # 用于提取该值的 XPath
    xpath_candidates: list[dict] = field(default_factory=list)  # XPath 候选列表
    confidence: float = 0.0  # 置信度 (0-1)
    extraction_method: str = "llm"  # 提取方法: llm, xpath, fuzzy_search
    error: str | None = None  # 错误信息（如果提取失败）


@dataclass
class PageExtractionRecord:
    """单页提取记录

    记录从一个详情页提取字段的完整过程。
    """

    url: str  # 详情页 URL
    fields: list[FieldExtractionResult] = field(default_factory=list)  # 字段提取结果
    nav_steps: list[dict] = field(default_factory=list)  # 导航步骤（用于重放）
    success: bool = False  # 是否成功提取所有必填字段
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def get_field(self, field_name: str) -> FieldExtractionResult | None:
        """获取指定字段的提取结果"""
        for f in self.fields:
            if f.field_name == field_name:
                return f
        return None

    def get_field_value(self, field_name: str) -> str | None:
        """获取指定字段的值"""
        field_result = self.get_field(field_name)
        return field_result.value if field_result else None


@dataclass
class CommonFieldXPath:
    """公共字段 XPath 模式"""

    field_name: str  # 字段名称
    xpath_pattern: str  # 公共 XPath 模式
    source_xpaths: list[str] = field(default_factory=list)  # 来源 XPath 列表
    confidence: float = 0.0  # 置信度
    validated: bool = False  # 是否已验证


@dataclass
class BatchExtractionResult:
    """批量提取结果"""

    # 探索阶段
    exploration_records: list[PageExtractionRecord] = field(default_factory=list)

    # 分析阶段
    common_xpaths: list[CommonFieldXPath] = field(default_factory=list)

    # 校验阶段
    validation_records: list[PageExtractionRecord] = field(default_factory=list)
    validation_success: bool = False

    # 元信息
    fields: list[FieldDefinition] = field(default_factory=list)  # 字段定义
    total_urls_explored: int = 0
    total_urls_validated: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def get_common_xpath(self, field_name: str) -> str | None:
        """获取指定字段的公共 XPath"""
        for xpath_info in self.common_xpaths:
            if xpath_info.field_name == field_name:
                return xpath_info.xpath_pattern
        return None

    def to_extraction_config(self) -> dict:
        """转换为提取配置（可用于批量爬取）"""
        return {
            "fields": [
                {
                    "name": f.name,
                    "description": f.description,
                    "xpath": self.get_common_xpath(f.name),
                    "required": f.required,
                    "data_type": f.data_type,
                }
                for f in self.fields
            ],
            "created_at": self.created_at,
        }
