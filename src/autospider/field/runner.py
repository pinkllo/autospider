"""字段提取流水线运行器。

该模块负责协调字段探索（BatchFieldExtractor）和基于 XPath 的批量提取（BatchXPathExtractor）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..common.config import config
from .models import FieldDefinition
from .batch_field_extractor import BatchFieldExtractor
from .batch_xpath_extractor import BatchXPathExtractor

if TYPE_CHECKING:
    from playwright.async_api import Page


async def run_field_pipeline(
    page: "Page",
    urls: list[str],
    fields: list[FieldDefinition],
    output_dir: str = "output",
    explore_count: int | None = None,
    validate_count: int | None = None,
    run_xpath: bool = True,
) -> dict:
    """运行字段提取流水线，包含探索规则和（可选的）批量 XPath 提取。

    该函数协调整个提取过程：
    1. 使用 BatchFieldExtractor 探索并生成通用的 XPath 提取规则。
    2. 使用生成的规则，通过 BatchXPathExtractor 进行全量 URL 数据的快速提取。

    Args:
        page: Playwright 页面对象。
        urls: 待处理的完整详情页 URL 列表。
        fields: 要提取的字段定义。
        output_dir: 结果和配置的输出目录。
        explore_count: 用于探索规则的样本数量（默认为配置中的值）。
        validate_count: 用于验证规则的样本数量（默认为配置中的值）。
        run_xpath: 完成探索后是否立即执行全量批量提取。

    Returns:
        包含执行过程和结论的字典。
    """
    # 从配置中读取默认值
    explore_count = explore_count or config.field_extractor.explore_count
    validate_count = validate_count or config.field_extractor.validate_count
    # 1. 初始化批量字段提取器，用于探索和生成 XPath 规则
    batch_extractor = BatchFieldExtractor(
        page=page,
        fields=fields,
        explore_count=explore_count,
        validate_count=validate_count,
        output_dir=output_dir,
    )

    # 2. 运行探索流程，生成提取配置
    batch_result = await batch_extractor.run(urls=urls)
    # 从结果中获取提取配置中的字段部分
    fields_config = batch_result.to_extraction_config().get("fields", [])

    xpath_result = None
    # 3. 如果启用了 XPath 提取且成功生成了配置，则进行批量提取
    if run_xpath and fields_config:
        xpath_extractor = BatchXPathExtractor(
            page=page,
            fields_config=fields_config,
            output_dir=output_dir,
        )
        xpath_result = await xpath_extractor.run(urls=urls)

    return {
        "batch_result": batch_result,
        "fields_config": fields_config,
        "xpath_result": xpath_result,
    }
