"""XPath 提取和模式分析模块"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ...common.logger import get_logger

if TYPE_CHECKING:
    from .models import DetailPageVisit


logger = get_logger(__name__)


class XPathExtractor:
    """XPath 提取器，负责从访问记录中提取公共 xpath"""

    def extract_common_xpath(self, detail_visits: list[DetailPageVisit]) -> str | None:
        """
        从探索记录中提取公共 xpath

        分析所有 detail_visits 的 xpath_candidates，找出最稳定的公共 xpath 模式
        """
        if len(detail_visits) < 2:
            return None

        logger.info(f"[XPathExtractor] 从 {len(detail_visits)} 个访问记录中提取公共 xpath...")

        # 收集所有 xpath（选择每个元素的最高优先级 xpath）
        xpaths = []
        for visit in detail_visits:
            if visit.clicked_element_xpath_candidates:
                # 按优先级排序
                sorted_candidates = sorted(
                    visit.clicked_element_xpath_candidates, key=lambda c: c.get("priority", 0)
                )
                if sorted_candidates:
                    xpaths.append(sorted_candidates[0]["xpath"])

        if not xpaths:
            logger.info("[XPathExtractor] ⚠ 未找到有效的 xpath")
            return None

        logger.info(f"[XPathExtractor] 提取到 {len(xpaths)} 个 xpath:")
        for xpath in xpaths:
            logger.info(f"  - {xpath}")

        # 找出公共模式
        common_pattern = self._find_common_xpath_pattern(xpaths)

        if common_pattern:
            logger.info(f"[XPathExtractor] ✓ 公共 xpath 模式: {common_pattern}")
        else:
            logger.info("[XPathExtractor] ⚠ 未找到公共 xpath 模式")

        return common_pattern

    def _find_common_xpath_pattern(self, xpaths: list[str]) -> str | None:
        """
        从一组 xpath 中找出公共模式（智能版）

        处理策略：
        1. 将XPath按节点分段
        2. 对每个节点位置进行智能对比
        3. 对于位置索引：如果所有XPath在该位置的索引相同则保留，不同则删除
        4. 对于属性选择器（如@class, @id）：保持不变

        例如:
        - 输入: [//section//ul/li[1]/a, //section//ul/li[2]/a]
          输出: //section//ul/li/a (li的索引变化，删除)
        - 输入: [//div[1]/ul/li[1]/a, //div[1]/ul/li[2]/a]
          输出: //div[1]/ul/li/a (div的索引固定，保留)
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
        - raw: 原始文本
        - tag: 标签名
        - index: 位置索引
        - attrs: 属性选择器列表
        - separator: 前导分隔符（"/" 或 "//"）
        """
        segments = []
        
        # 匹配XPath节点段
        pattern = r'(//?)([a-zA-Z*][\w-]*)(\[[^\]]+\])*'
        
        for match in re.finditer(pattern, xpath):
            separator = match.group(1)
            tag = match.group(2)
            predicates_raw = match.group(3) or ""
            
            index = None
            attrs = []
            
            for pred_match in re.finditer(r'\[([^\]]+)\]', predicates_raw):
                pred = pred_match.group(1)
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
        """
        if len(xpaths) < 2:
            return xpaths[0] if xpaths else None

        # 解析所有XPath
        all_segments = [self._parse_xpath_segments(xpath) for xpath in xpaths]
        
        # 检查节点数量是否一致
        segment_counts = [len(segs) for segs in all_segments]
        if len(set(segment_counts)) > 1:
            logger.debug(f"[XPathExtractor] XPath节点数量不一致: {segment_counts}")
            from collections import Counter
            count_freq = Counter(segment_counts)
            most_common_count = count_freq.most_common(1)[0][0]
            
            filtered_xpaths = [
                xpaths[i] for i, segs in enumerate(all_segments) 
                if len(segs) == most_common_count
            ]
            if len(filtered_xpaths) < 2:
                return None
            
            all_segments = [self._parse_xpath_segments(xpath) for xpath in filtered_xpaths]
            xpaths = filtered_xpaths

        num_segments = len(all_segments[0])
        result_parts = []
        
        for seg_idx in range(num_segments):
            tags = [segs[seg_idx]["tag"] for segs in all_segments]
            indices = [segs[seg_idx]["index"] for segs in all_segments]
            all_attrs = [segs[seg_idx]["attrs"] for segs in all_segments]
            separators = [segs[seg_idx]["separator"] for segs in all_segments]
            
            if len(set(tags)) > 1:
                logger.debug(f"[XPathExtractor] 位置 {seg_idx} 标签不一致: {set(tags)}")
                return None
            
            tag = tags[0]
            separator = separators[0]
            
            # 判断索引是否应该保留
            non_none_indices = [i for i in indices if i is not None]
            
            keep_index = False
            index_value = None
            if non_none_indices:
                if len(set(non_none_indices)) == 1 and len(non_none_indices) == len(indices):
                    keep_index = True
                    index_value = non_none_indices[0]
            
            # 合并属性选择器
            common_attrs = self._merge_attributes(all_attrs)
            
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
        
        logger.info(f"[XPathExtractor] 智能提取模式: {result}")
        logger.info(f"[XPathExtractor] 置信度: {confidence:.2%}")
        
        if confidence >= 0.6:
            return result
        else:
            return None

    def _merge_attributes(self, all_attrs: list[list[str]]) -> list[str]:
        """合并属性选择器（取交集）"""
        if not all_attrs or not all_attrs[0]:
            return []
        
        common = set(all_attrs[0])
        for attrs in all_attrs[1:]:
            common &= set(attrs)
        
        return sorted(list(common))

    def _calculate_pattern_confidence(self, original_xpaths: list[str], pattern: str) -> float:
        """计算模式的置信度"""
        matching = 0
        pattern_normalized = re.sub(r'\[\d+\]', '', pattern)
        
        for xpath in original_xpaths:
            xpath_normalized = re.sub(r'\[\d+\]', '', xpath)
            if xpath_normalized == pattern_normalized:
                matching += 1
        
        return matching / len(original_xpaths) if original_xpaths else 0

    def _fallback_extract_pattern(self, xpaths: list[str]) -> str | None:
        """回退方案：简单的索引删除策略"""
        logger.debug("[XPathExtractor] 使用回退策略提取模式")
        
        from collections import Counter
        
        normalized = []
        for xpath in xpaths:
            norm = re.sub(r"\[\d+\]", "", xpath)
            normalized.append(norm)

        pattern_counts = Counter(normalized)
        most_common = pattern_counts.most_common(1)

        if not most_common:
            return None

        common_pattern, count = most_common[0]
        confidence = count / len(xpaths)

        logger.info(
            f"[XPathExtractor] (回退)最常见模式: {common_pattern}, 出现 {count}/{len(xpaths)} 次 (置信度: {confidence:.2%})"
        )

        if confidence >= 0.6:
            return common_pattern
        else:
            return None
