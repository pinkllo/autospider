"""字段 XPath 模式提取器

从多个页面的提取记录中提取公共 XPath 模式。
复用 URL 收集器模块的 XPath 模式匹配逻辑。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

from .models import (
    PageExtractionRecord,
    CommonFieldXPath,
)

if TYPE_CHECKING:
    from playwright.async_api import Page


class FieldXPathExtractor:
    """字段 XPath 模式提取器

    从多个页面的提取记录中分析每个字段的 XPath，
    提取出公共模式，用于批量爬取。
    """

    def extract_common_pattern(
        self,
        records: list[PageExtractionRecord],
        field_name: str,
    ) -> CommonFieldXPath | None:
        """
        从多个页面记录中提取公共 XPath 模式

        Args:
            records: 页面提取记录列表
            field_name: 字段名称

        Returns:
            公共 XPath 模式，如果无法提取则返回 None
        """
        if len(records) < 2:
            print(f"[FieldXPathExtractor] 记录数不足: {len(records)}")
            return None

        print(
            f"[FieldXPathExtractor] 从 {len(records)} 条记录中提取字段 '{field_name}' 的公共 XPath..."
        )

        # 收集所有 XPath
        xpaths = []
        for record in records:
            field_result = record.get_field(field_name)
            if field_result and field_result.xpath:
                xpaths.append(field_result.xpath)

        if not xpaths:
            print("[FieldXPathExtractor] ⚠ 未找到有效的 XPath")
            return None

        print(f"[FieldXPathExtractor] 收集到 {len(xpaths)} 个 XPath:")
        for xpath in xpaths:
            print(f"  - {xpath}")

        # 找出公共模式
        common_pattern = self._find_common_xpath_pattern(xpaths)

        if not common_pattern:
            print("[FieldXPathExtractor] ⚠ 未找到公共 XPath 模式")
            return None

        print(f"[FieldXPathExtractor] ✓ 公共 XPath 模式: {common_pattern}")

        # 计算置信度
        normalized_count = self._count_matching_pattern(xpaths, common_pattern)
        confidence = normalized_count / len(xpaths)

        return CommonFieldXPath(
            field_name=field_name,
            xpath_pattern=common_pattern,
            source_xpaths=xpaths,
            confidence=confidence,
        )

    def _find_common_xpath_pattern(self, xpaths: list[str]) -> str | None:
        """
        从一组 XPath 中找出公共模式

        处理策略：
        1. 去除索引（如 [1], [2]）
        2. 统计最常见的模式
        3. 返回出现频率超过阈值的模式

        Examples:
            - //div[@class="title"]/span[1] -> //div[@class="title"]/span
            - //div[@class="title"]/span[2] -> //div[@class="title"]/span
        """
        if not xpaths:
            return None

        # 去掉索引，标准化
        normalized = []
        for xpath in xpaths:
            # 去掉所有的位置索引 [数字]
            norm = re.sub(r"\[\d+\]", "", xpath)
            normalized.append(norm)

        # 统计模式出现次数
        pattern_counts = Counter(normalized)
        most_common = pattern_counts.most_common(1)

        if not most_common:
            return None

        common_pattern, count = most_common[0]
        confidence = count / len(xpaths)

        print(f"[FieldXPathExtractor] 最常见模式: {common_pattern}")
        print(f"[FieldXPathExtractor] 出现次数: {count}/{len(xpaths)} (置信度: {confidence:.2%})")

        # 置信度阈值
        if confidence >= 0.5:
            return common_pattern
        else:
            return None

    def _count_matching_pattern(self, xpaths: list[str], pattern: str) -> int:
        """统计匹配公共模式的 XPath 数量"""
        count = 0
        for xpath in xpaths:
            normalized = re.sub(r"\[\d+\]", "", xpath)
            if normalized == pattern:
                count += 1
        return count

    def extract_all_common_patterns(
        self,
        records: list[PageExtractionRecord],
        field_names: list[str],
    ) -> list[CommonFieldXPath]:
        """
        提取所有字段的公共 XPath 模式

        Args:
            records: 页面提取记录列表
            field_names: 字段名称列表

        Returns:
            公共 XPath 模式列表
        """
        patterns = []

        for field_name in field_names:
            pattern = self.extract_common_pattern(records, field_name)
            if pattern:
                patterns.append(pattern)

        return patterns


async def validate_xpath_pattern(
    page: "Page",
    url: str,
    xpath_pattern: str,
    expected_value: str | None = None,
) -> tuple[bool, str | None]:
    """
    验证 XPath 模式是否能正确提取字段

    Args:
        page: Playwright 页面对象
        url: 验证用的 URL
        xpath_pattern: XPath 模式
        expected_value: 预期值（可选，用于对比）

    Returns:
        (验证是否通过, 提取到的值)
    """
    try:
        # 导航到页面
        await page.goto(url, wait_until="domcontentloaded")

        # 使用 XPath 提取
        element = page.locator(f"xpath={xpath_pattern}").first
        value = await element.inner_text(timeout=5000)
        value = value.strip()

        if not value:
            return False, None

        # 如果有预期值，对比
        if expected_value:
            # 模糊匹配
            expected_normalized = expected_value.strip().lower()
            actual_normalized = value.lower()

            if expected_normalized in actual_normalized or actual_normalized in expected_normalized:
                return True, value

            # 计算相似度
            from difflib import SequenceMatcher

            similarity = SequenceMatcher(None, expected_normalized, actual_normalized).ratio()

            return similarity >= 0.7, value

        # 没有预期值，只要能提取到内容就算成功
        return True, value

    except Exception as e:
        print(f"[validate_xpath_pattern] 验证失败: {e}")
        return False, None
