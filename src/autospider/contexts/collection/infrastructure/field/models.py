"""字段提取数据模型定义"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from autospider.contexts.collection.domain.fields import FieldDefinition, build_field_definitions


def _normalize_xpath_fallbacks(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    normalized: list[str] = []
    for item in value:
        xpath = str(item or "").strip()
        if xpath:
            normalized.append(xpath)
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class FieldRule:
    """字段提取规则的内部规范类型。"""

    field: FieldDefinition
    xpath: str | None = None
    xpath_fallbacks: tuple[str, ...] = ()
    xpath_candidate_pool: tuple[str, ...] = ()
    detail_template_signature: str = ""
    field_signature: str = ""
    xpath_validated: bool = False

    @property
    def name(self) -> str:
        return self.field.name

    @property
    def description(self) -> str:
        return self.field.description

    @property
    def required(self) -> bool:
        return self.field.required

    @property
    def data_type(self) -> str:
        return self.field.data_type

    @property
    def extraction_source(self) -> str | None:
        return self.field.extraction_source

    @property
    def fixed_value(self) -> str | None:
        return self.field.fixed_value

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "FieldRule":
        xpath = str(payload.get("xpath") or "").strip() or None
        fallbacks = _normalize_xpath_fallbacks(payload.get("xpath_fallbacks"))
        field = build_field_definitions([payload])[0]
        return cls(
            field=field,
            xpath=xpath,
            xpath_fallbacks=fallbacks,
            xpath_candidate_pool=_normalize_xpath_fallbacks(payload.get("xpath_candidate_pool")),
            detail_template_signature=str(payload.get("detail_template_signature") or "").strip(),
            field_signature=str(payload.get("field_signature") or "").strip(),
            xpath_validated=bool(payload.get("xpath_validated", xpath is not None)),
        )

    @classmethod
    def from_xpath(
        cls,
        field: FieldDefinition,
        common_xpath: "CommonFieldXPath | None" = None,
    ) -> "FieldRule":
        if common_xpath is None:
            return cls(field=field)
        return cls(
            field=field,
            xpath=str(common_xpath.xpath_pattern or "").strip() or None,
            xpath_fallbacks=_normalize_xpath_fallbacks(common_xpath.fallback_xpaths),
            xpath_validated=bool(common_xpath.validated),
        )

    def has_rule_candidate(self) -> bool:
        return bool(self.xpath or self.xpath_fallbacks)

    def to_payload(self) -> dict[str, Any]:
        payload = self.field.to_payload()
        payload["xpath"] = self.xpath
        payload["xpath_fallbacks"] = list(self.xpath_fallbacks)
        payload["xpath_candidate_pool"] = list(self.xpath_candidate_pool)
        payload["detail_template_signature"] = self.detail_template_signature
        payload["field_signature"] = self.field_signature
        payload["xpath_validated"] = self.xpath_validated
        return payload


@dataclass(frozen=True, slots=True)
class ExtractionConfig:
    """字段提取配置的内部规范类型。"""

    fields: tuple[FieldRule, ...] = ()
    created_at: str = ""

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ExtractionConfig":
        raw_fields = payload.get("fields")
        fields: list[FieldRule] = []
        if isinstance(raw_fields, Sequence) and not isinstance(raw_fields, (str, bytes)):
            for item in raw_fields:
                if isinstance(item, Mapping):
                    fields.append(FieldRule.from_payload(item))
        return cls(fields=tuple(fields), created_at=str(payload.get("created_at") or ""))

    def to_payload(self) -> dict[str, Any]:
        return {
            "fields": [rule.to_payload() for rule in self.fields],
            "created_at": self.created_at,
        }


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
    salvaged: bool = False  # 是否通过批处理挽救机制修复
    salvage_reason: str | None = None  # 挽救阶段的结果原因（成功/失败）
    salvage_trace: dict = field(default_factory=dict)  # 挽救过程轨迹


@dataclass
class PageExtractionRecord:
    """单页提取记录

    记录从一个详情页提取字段的完整过程。
    """

    url: str  # 详情页 URL
    fields: list[FieldExtractionResult] = field(default_factory=list)  # 字段提取结果
    nav_steps: list[dict] = field(default_factory=list)  # 导航步骤（用于重放）
    success: bool = False  # 是否成功提取所有必填字段
    timestamp: str = ""

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
    fallback_xpaths: list[str] = field(default_factory=list)  # 失败时按顺序回退的 XPath
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
    created_at: str = ""

    def get_common_xpath(self, field_name: str) -> str | None:
        """获取指定字段的公共 XPath"""
        for xpath_info in self.common_xpaths:
            if xpath_info.field_name == field_name:
                return xpath_info.xpath_pattern
        return None

    def to_extraction_config_model(self) -> ExtractionConfig:
        """转换为提取配置模型（可用于批量爬取）"""
        validation_available = self.total_urls_validated > 0
        xpath_map = {x.field_name: x for x in self.common_xpaths}
        rules = [
            FieldRule.from_xpath(
                f,
                (
                    xpath_map.get(f.name)
                    if f.name in xpath_map
                    and (not validation_available or xpath_map[f.name].validated)
                    else None
                ),
            )
            for f in self.fields
        ]
        return ExtractionConfig(fields=tuple(rules), created_at=self.created_at)

    def to_extraction_config(self) -> dict:
        """转换为提取配置（可用于批量爬取）"""
        return self.to_extraction_config_model().to_payload()
