"""HTML 文本模糊搜索工具

用于在 HTML 中定位目标文本，支持模糊匹配和 XPath 生成。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from difflib import SequenceMatcher

from lxml import html as lxml_html
from lxml.etree import _Element

if TYPE_CHECKING:
    pass


@dataclass
class TextMatch:
    """文本匹配结果"""

    text: str  # 匹配到的文本
    similarity: float  # 相似度 (0-1)
    element_xpath: str  # 包含该文本的元素的 XPath
    element_tag: str  # 元素标签名
    element_text_content: str  # 元素的完整文本内容
    position: int = 0  # 在页面中的位置索引（用于消歧）


class FuzzyTextSearcher:
    """HTML 文本模糊搜索器

    用于在 HTML 中搜索目标文本，返回匹配结果列表。
    支持模糊匹配，可用于处理 LLM 输出与实际 HTML 文本略有差异的情况。
    """

    def __init__(self, threshold: float = 0.8):
        """
        初始化搜索器

        Args:
            threshold: 模糊匹配阈值 (0-1)，低于此值的匹配将被忽略
        """
        self.threshold = threshold

    def search_in_html(
        self, html_content: str, target_text: str, threshold: float | None = None
    ) -> list[TextMatch]:
        """
        在 HTML 中搜索目标文本

        Args:
            html_content: HTML 内容
            target_text: 要搜索的目标文本
            threshold: 可选的匹配阈值，覆盖默认值

        Returns:
            匹配结果列表，按相似度降序排列
        """
        if not target_text or not html_content:
            return []

        threshold = threshold or self.threshold

        try:
            tree = lxml_html.fromstring(html_content)
        except Exception:
            # 如果解析失败，尝试作为片段解析
            try:
                tree = lxml_html.fragment_fromstring(html_content, create_parent="div")
            except Exception:
                return []

        matches = []
        position = 0

        # 遍历所有文本节点
        for element in tree.iter():
            if element.text:
                match = self._check_text_match(
                    element, element.text, target_text, threshold, position
                )
                if match:
                    matches.append(match)
                position += 1

            if element.tail:
                # tail 属于父元素
                parent = element.getparent()
                if parent is not None:
                    match = self._check_text_match(
                        parent, element.tail, target_text, threshold, position
                    )
                    if match:
                        matches.append(match)
                position += 1

        # 按相似度降序排列
        matches.sort(key=lambda m: m.similarity, reverse=True)

        return matches

    def _check_text_match(
        self,
        element: _Element,
        text: str,
        target_text: str,
        threshold: float,
        position: int,
    ) -> TextMatch | None:
        """检查文本是否匹配目标"""
        text = text.strip()
        if not text:
            return None

        # 计算相似度
        similarity = self._calculate_similarity(text, target_text)

        if similarity >= threshold:
            # 生成 XPath
            xpath = self._generate_xpath(element)

            return TextMatch(
                text=text,
                similarity=similarity,
                element_xpath=xpath,
                element_tag=element.tag,
                element_text_content=self._get_full_text(element),
                position=position,
            )

        return None

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """计算两个文本的相似度"""
        # 标准化文本：去除多余空白、转小写
        norm1 = self._normalize_text(text1)
        norm2 = self._normalize_text(text2)

        # 完全匹配
        if norm1 == norm2:
            return 1.0

        # 包含匹配（一个是另一个的子串）
        if norm1 in norm2 or norm2 in norm1:
            return 0.95

        # 使用 SequenceMatcher 计算相似度
        return SequenceMatcher(None, norm1, norm2).ratio()

    def _normalize_text(self, text: str) -> str:
        """标准化文本以便比较"""
        # 去除多余空白
        text = re.sub(r"\s+", " ", text).strip()
        # 转小写
        text = text.lower()
        return text

    def _generate_xpath(self, element: _Element) -> str:
        """
        为元素生成 XPath

        生成策略优先级：
        1. 使用 id 属性
        2. 使用 class + 标签组合
        3. 使用相对路径
        """
        # 尝试使用 id
        elem_id = element.get("id")
        if elem_id:
            return f'//*[@id="{elem_id}"]'

        # 收集路径组件
        path_parts = []
        current = element

        while current is not None and current.tag != "html":
            # 获取同类兄弟节点的索引
            parent = current.getparent()
            if parent is not None:
                siblings = [c for c in parent if c.tag == current.tag]
                if len(siblings) > 1:
                    index = siblings.index(current) + 1
                    path_parts.append(f"{current.tag}[{index}]")
                else:
                    path_parts.append(current.tag)
            else:
                path_parts.append(current.tag)

            current = parent

        path_parts.reverse()
        return "//" + "/".join(path_parts)

    def _get_full_text(self, element: _Element) -> str:
        """获取元素的完整文本内容"""
        return "".join(element.itertext()).strip()

    def search_exact(self, html_content: str, target_text: str) -> list[TextMatch]:
        """
        精确搜索（相似度阈值为 1.0）

        Args:
            html_content: HTML 内容
            target_text: 要搜索的目标文本

        Returns:
            精确匹配结果列表
        """
        return self.search_in_html(html_content, target_text, threshold=0.99)

    def get_best_match(
        self, html_content: str, target_text: str, threshold: float | None = None
    ) -> TextMatch | None:
        """
        获取最佳匹配结果

        Args:
            html_content: HTML 内容
            target_text: 要搜索的目标文本
            threshold: 可选的匹配阈值

        Returns:
            最佳匹配结果，如果没有匹配则返回 None
        """
        matches = self.search_in_html(html_content, target_text, threshold)
        return matches[0] if matches else None


def search_text_in_html(
    html_content: str, target_text: str, threshold: float = 0.8
) -> list[TextMatch]:
    """
    便捷函数：在 HTML 中搜索目标文本

    Args:
        html_content: HTML 内容
        target_text: 要搜索的目标文本
        threshold: 模糊匹配阈值 (0-1)

    Returns:
        匹配结果列表
    """
    searcher = FuzzyTextSearcher(threshold=threshold)
    return searcher.search_in_html(html_content, target_text)
