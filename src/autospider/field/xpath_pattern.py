"""字段 XPath 模式提取器

从多个页面的提取记录中提取公共 XPath 模式。
复用 URL 收集器模块的 XPath 模式匹配逻辑。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

from ..common.logger import get_logger
from .models import (
    PageExtractionRecord,
    CommonFieldXPath,
)

if TYPE_CHECKING:
    from playwright.async_api import Page


logger = get_logger(__name__)


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
            logger.info(f"[FieldXPathExtractor] 记录数不足: {len(records)}")
            return None

        logger.info(
            f"[FieldXPathExtractor] 从 {len(records)} 条记录中提取字段 '{field_name}' 的公共 XPath..."
        )

        # 收集所有 XPath
        xpaths = []
        for record in records:
            field_result = record.get_field(field_name)
            if field_result and field_result.xpath:
                xpaths.append(field_result.xpath)

        if not xpaths:
            logger.info("[FieldXPathExtractor] ⚠ 未找到有效的 XPath")
            return None

        logger.info(f"[FieldXPathExtractor] 收集到 {len(xpaths)} 个 XPath:")
        for xpath in xpaths:
            logger.info(f"  - {xpath}")

        # 找出公共模式
        common_pattern = self._find_common_xpath_pattern(xpaths)

        if not common_pattern:
            logger.info("[FieldXPathExtractor] ⚠ 未找到公共 XPath 模式")
            return None

        logger.info(f"[FieldXPathExtractor] ✓ 公共 XPath 模式: {common_pattern}")

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
        从一组 XPath 中找出公共模式（智能版）

        处理策略：
        1. 将XPath按节点分段
        2. 对每个节点位置进行智能对比
        3. 对于位置索引：如果所有XPath在该位置的索引相同则保留，不同则删除
        4. 对于属性选择器（如@class, @id）：保持不变
        5. 统计最常见的模式并返回置信度

        Examples:
            - 输入: [//div/ul/li[1]/a, //div/ul/li[2]/a, //div/ul/li[3]/a]
              输出: //div/ul/li/a (索引变化，删除)
            - 输入: [//div[1]/ul/li[1]/a, //div[1]/ul/li[2]/a]
              输出: //div[1]/ul/li/a (div的索引固定，保留；li的索引变化，删除)
        """
        if not xpaths:
            return None

        # 使用智能节点对比方法
        smart_pattern = self._smart_extract_common_pattern(xpaths)
        if smart_pattern:
            return smart_pattern

        # 如果智能方法失败，回退到简化策略
        return self._fallback_extract_pattern(xpaths)

    def _parse_xpath_segments(self, xpath: str) -> list[dict]:
        """
        解析XPath为节点段列表
        
        每个节点段包含：
        - raw: 原始文本（如 "div[1]" 或 "a[@class='link']"）
        - tag: 标签名（如 "div", "a"）
        - index: 位置索引（如 1, 2, None）
        - attrs: 属性选择器列表
        - separator: 前导分隔符（"/" 或 "//"）
        """
        segments = []
        
        # 匹配XPath节点段，支持 / 和 // 分隔
        # 模式：匹配 //tag[...] 或 /tag[...]
        pattern = r'(//?)([a-zA-Z*][\w-]*)(\[[^\]]+\])*'
        
        for match in re.finditer(pattern, xpath):
            separator = match.group(1)  # "/" 或 "//"
            tag = match.group(2)  # 标签名
            predicates_raw = match.group(3) or ""  # 所有谓词 [...]
            
            # 解析谓词
            index = None
            attrs = []
            
            # 提取所有谓词
            for pred_match in re.finditer(r'\[([^\]]+)\]', predicates_raw):
                pred = pred_match.group(1)
                # 判断是位置索引还是属性选择器
                if re.match(r'^\d+$', pred.strip()):
                    index = int(pred.strip())
                else:
                    attrs.append(f"[{pred}]")
            
            segments.append({
                "raw": match.group(0),
                "tag": tag,
                "index": index,
                "attrs": attrs,
                "separator": separator,
            })
        
        return segments

    def _smart_extract_common_pattern(self, xpaths: list[str]) -> str | None:
        """
        智能提取公共XPath模式
        
        对比所有XPath的节点段，对每个位置：
        - 如果标签名不同，则无法合并
        - 如果索引相同，则保留索引
        - 如果索引不同，则删除索引
        - 属性选择器保持不变
        """
        if len(xpaths) < 2:
            return xpaths[0] if xpaths else None

        # 解析所有XPath
        all_segments = [self._parse_xpath_segments(xpath) for xpath in xpaths]
        
        # 检查节点数量是否一致
        segment_counts = [len(segs) for segs in all_segments]
        if len(set(segment_counts)) > 1:
            logger.debug(f"[FieldXPathExtractor] XPath节点数量不一致: {segment_counts}")
            # 尝试找出最常见的节点数量，只处理相同长度的XPath
            from collections import Counter
            count_freq = Counter(segment_counts)
            most_common_count = count_freq.most_common(1)[0][0]
            
            # 过滤出相同长度的XPath
            filtered_xpaths = [
                xpaths[i] for i, segs in enumerate(all_segments) 
                if len(segs) == most_common_count
            ]
            if len(filtered_xpaths) < 2:
                return None
            
            # 重新解析
            all_segments = [self._parse_xpath_segments(xpath) for xpath in filtered_xpaths]
            xpaths = filtered_xpaths

        num_segments = len(all_segments[0])
        
        # 构建公共模式
        result_parts = []
        
        for seg_idx in range(num_segments):
            # 收集该位置所有节点的信息
            tags = [segs[seg_idx]["tag"] for segs in all_segments]
            indices = [segs[seg_idx]["index"] for segs in all_segments]
            all_attrs = [segs[seg_idx]["attrs"] for segs in all_segments]
            separators = [segs[seg_idx]["separator"] for segs in all_segments]
            
            # 标签必须一致
            if len(set(tags)) > 1:
                logger.debug(f"[FieldXPathExtractor] 位置 {seg_idx} 标签不一致: {set(tags)}")
                return None
            
            tag = tags[0]
            separator = separators[0]  # 分隔符应该一致
            
            # 判断索引是否应该保留
            # 规则：如果所有非None索引值相同，则保留；否则删除
            non_none_indices = [i for i in indices if i is not None]
            
            keep_index = False
            index_value = None
            if non_none_indices:
                if len(set(non_none_indices)) == 1 and len(non_none_indices) == len(indices):
                    # 所有XPath在该位置都有相同的索引
                    keep_index = True
                    index_value = non_none_indices[0]
            
            # 合并属性选择器（取交集或最常见的）
            common_attrs = self._merge_attributes(all_attrs)
            
            # 构建节点表达式
            node_expr = f"{separator}{tag}"
            if keep_index:
                node_expr += f"[{index_value}]"
            if common_attrs:
                node_expr += "".join(common_attrs)
            
            result_parts.append(node_expr)
        
        if not result_parts:
            return None
        
        result = "".join(result_parts)
        
        # 验证置信度
        confidence = self._calculate_pattern_confidence(xpaths, result)
        
        logger.info(f"[FieldXPathExtractor] 智能提取模式: {result}")
        logger.info(f"[FieldXPathExtractor] 置信度: {confidence:.2%}")
        
        if confidence >= 0.5:
            return result
        else:
            return None

    def _merge_attributes(self, all_attrs: list[list[str]]) -> list[str]:
        """
        合并多个XPath节点的属性选择器
        
        策略：取所有XPath共有的属性选择器
        """
        if not all_attrs:
            return []
        
        # 取交集
        if not all_attrs[0]:
            return []
        
        common = set(all_attrs[0])
        for attrs in all_attrs[1:]:
            common &= set(attrs)
        
        return sorted(list(common))

    def _calculate_pattern_confidence(self, original_xpaths: list[str], pattern: str) -> float:
        """
        计算模式的置信度
        
        通过标准化原始XPath和模式进行比较
        """
        matching = 0
        pattern_normalized = self._normalize_for_comparison(pattern)
        
        for xpath in original_xpaths:
            xpath_normalized = self._normalize_for_comparison(xpath)
            if xpath_normalized == pattern_normalized:
                matching += 1
        
        return matching / len(original_xpaths) if original_xpaths else 0

    def _normalize_for_comparison(self, xpath: str) -> str:
        """
        标准化XPath用于比较
        
        只删除变化的位置索引，保留属性选择器
        """
        # 删除位置索引（纯数字的谓词）
        return re.sub(r'\[\d+\]', '', xpath)

    def _fallback_extract_pattern(self, xpaths: list[str]) -> str | None:
        """
        回退方案：简单的索引删除策略
        
        当智能策略失败时使用
        """
        logger.debug("[FieldXPathExtractor] 使用回退策略提取模式")
        
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

        logger.info(f"[FieldXPathExtractor] (回退)最常见模式: {common_pattern}")
        logger.info(f"[FieldXPathExtractor] (回退)出现次数: {count}/{len(xpaths)} (置信度: {confidence:.2%})")

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
        logger.info(f"[validate_xpath_pattern] 验证失败: {e}")
        return False, None
