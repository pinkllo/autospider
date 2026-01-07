"""XPath 提取和模式分析模块"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import DetailPageVisit


class XPathExtractor:
    """XPath 提取器，负责从访问记录中提取公共 xpath"""
    
    def extract_common_xpath(self, detail_visits: list[DetailPageVisit]) -> str | None:
        """
        从探索记录中提取公共 xpath
        
        分析所有 detail_visits 的 xpath_candidates，找出最稳定的公共 xpath 模式
        """
        if len(detail_visits) < 2:
            return None
        
        print(f"[XPathExtractor] 从 {len(detail_visits)} 个访问记录中提取公共 xpath...")
        
        # 收集所有 xpath（选择每个元素的最高优先级 xpath）
        xpaths = []
        for visit in detail_visits:
            if visit.clicked_element_xpath_candidates:
                # 按优先级排序
                sorted_candidates = sorted(
                    visit.clicked_element_xpath_candidates,
                    key=lambda c: c.get("priority", 0),
                    reverse=True
                )
                if sorted_candidates:
                    xpaths.append(sorted_candidates[0]["xpath"])
        
        if not xpaths:
            print(f"[XPathExtractor] ⚠ 未找到有效的 xpath")
            return None
        
        print(f"[XPathExtractor] 提取到 {len(xpaths)} 个 xpath:")
        for xpath in xpaths:
            print(f"  - {xpath}")
        
        # 找出公共模式
        common_pattern = self._find_common_xpath_pattern(xpaths)
        
        if common_pattern:
            print(f"[XPathExtractor] ✓ 公共 xpath 模式: {common_pattern}")
        else:
            print(f"[XPathExtractor] ⚠ 未找到公共 xpath 模式")
        
        return common_pattern
    
    def _find_common_xpath_pattern(self, xpaths: list[str]) -> str | None:
        """
        从一组 xpath 中找出公共模式
        
        例如:
        - //section//ul/li[1]/a -> //section//ul/li/a
        - //section//ul/li[2]/a -> //section//ul/li/a
        """
        if not xpaths:
            return None
        
        # 去掉索引，找公共前缀
        normalized = []
        for xpath in xpaths:
            # 去掉所有的索引 [数字]
            norm = re.sub(r'\[\d+\]', '', xpath)
            normalized.append(norm)
        
        # 找出最常见的模式
        from collections import Counter
        pattern_counts = Counter(normalized)
        most_common = pattern_counts.most_common(1)
        
        if not most_common:
            return None
        
        common_pattern, count = most_common[0]
        confidence = count / len(xpaths)
        
        print(f"[XPathExtractor] 最常见模式: {common_pattern}, 出现 {count}/{len(xpaths)} 次 (置信度: {confidence:.2%})")
        
        # 只有当大部分 xpath 都符合这个模式时，才认为是可靠的
        if confidence >= 0.6:
            return common_pattern
        else:
            return None
