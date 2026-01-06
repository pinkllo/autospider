"""mark_id 验证器

用于验证 LLM 返回的 mark_id 与文本是否与实际的 SoM 元素匹配。
解决视觉模型可能将不属于某个文本的 mark_id 错误识别的问题。
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from .config import config

if TYPE_CHECKING:
    from .types import SoMSnapshot, ElementMark


class MarkIdValidationResult:
    """mark_id 验证结果"""
    
    def __init__(
        self,
        mark_id: int,
        llm_text: str,
        actual_text: str,
        similarity: float,
        is_valid: bool,
        element: "ElementMark | None" = None,
    ):
        self.mark_id = mark_id
        self.llm_text = llm_text  # LLM 返回的文本
        self.actual_text = actual_text  # 实际元素的文本
        self.similarity = similarity  # 相似度分数
        self.is_valid = is_valid  # 是否验证通过
        self.element = element  # 对应的元素（如果找到）
    
    def __repr__(self) -> str:
        status = "✓" if self.is_valid else "✗"
        return f"[{self.mark_id}] {status} sim={self.similarity:.2f} | LLM: '{self.llm_text[:30]}...' vs Actual: '{self.actual_text[:30]}...'"


class MarkIdValidator:
    """mark_id 验证器
    
    验证 LLM 返回的 mark_id 与文本映射是否与实际的 SoM snapshot 匹配。
    """
    
    def __init__(
        self,
        threshold: float | None = None,
        debug: bool | None = None,
    ):
        """初始化验证器
        
        Args:
            threshold: 相似度阈值，默认从配置读取
            debug: 是否打印调试信息，默认从配置读取
        """
        self.threshold = threshold if threshold is not None else config.url_collector.mark_id_match_threshold
        self.debug = debug if debug is not None else config.url_collector.debug_mark_id_validation
    
    def validate_mark_id_text_map(
        self,
        mark_id_text_map: dict[str, str],
        snapshot: "SoMSnapshot",
    ) -> tuple[list[int], list[MarkIdValidationResult]]:
        """验证 LLM 返回的 mark_id 与文本映射
        
        Args:
            mark_id_text_map: LLM 返回的 {mark_id: text} 映射（mark_id 为字符串）
            snapshot: SoM 快照
            
        Returns:
            (valid_mark_ids, validation_results): 验证通过的 mark_id 列表和所有验证结果
        """
        valid_mark_ids = []
        results = []
        
        # 构建 mark_id -> element 的映射
        mark_id_to_element = {m.mark_id: m for m in snapshot.marks}
        
        for mark_id_str, llm_text in mark_id_text_map.items():
            try:
                mark_id = int(mark_id_str)
            except ValueError:
                if self.debug:
                    print(f"[Validator] ⚠ 无效的 mark_id: {mark_id_str}")
                continue
            
            element = mark_id_to_element.get(mark_id)
            
            if element is None:
                # mark_id 不存在于当前快照中
                result = MarkIdValidationResult(
                    mark_id=mark_id,
                    llm_text=llm_text,
                    actual_text="[元素不存在]",
                    similarity=0.0,
                    is_valid=False,
                    element=None,
                )
                results.append(result)
                if self.debug:
                    print(f"[Validator] ✗ mark_id={mark_id} 不存在于当前页面")
                continue
            
            # 获取元素的实际文本
            actual_text = element.text or ""
            
            # 计算相似度
            similarity = self._calculate_similarity(llm_text, actual_text)
            
            # 判断是否通过验证
            is_valid = similarity >= self.threshold
            
            result = MarkIdValidationResult(
                mark_id=mark_id,
                llm_text=llm_text,
                actual_text=actual_text,
                similarity=similarity,
                is_valid=is_valid,
                element=element,
            )
            results.append(result)
            
            if is_valid:
                valid_mark_ids.append(mark_id)
                if self.debug:
                    print(f"[Validator] ✓ mark_id={mark_id} 验证通过 (sim={similarity:.2f})")
                    print(f"            LLM: '{llm_text[:50]}...'")
                    print(f"            实际: '{actual_text[:50]}...'")
            else:
                if self.debug:
                    print(f"[Validator] ✗ mark_id={mark_id} 验证失败 (sim={similarity:.2f} < {self.threshold})")
                    print(f"            LLM: '{llm_text[:50]}...'")
                    print(f"            实际: '{actual_text[:50]}...'")
        
        return valid_mark_ids, results
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """计算两个文本的相似度
        
        使用多种策略：
        1. 完全包含检查
        2. 归一化后的序列匹配
        3. 关键词重叠
        
        Args:
            text1: 第一个文本（LLM 返回的）
            text2: 第二个文本（实际元素的）
            
        Returns:
            相似度分数 (0-1)
        """
        if not text1 or not text2:
            return 0.0
        
        # 归一化：去除多余空格、转小写
        norm1 = self._normalize_text(text1)
        norm2 = self._normalize_text(text2)
        
        if not norm1 or not norm2:
            return 0.0
        
        # 策略1：完全匹配
        if norm1 == norm2:
            return 1.0
        
        # 策略2：包含关系（一个是另一个的子串）
        if norm1 in norm2 or norm2 in norm1:
            shorter = min(len(norm1), len(norm2))
            longer = max(len(norm1), len(norm2))
            length_ratio = shorter / longer
            
            # 如果 LLM 文本是实际文本的前缀，说明 LLM 正确识别了元素但只返回了部分文本
            # 这种情况应该给予更高的分数
            if norm2.startswith(norm1) and len(norm1) >= 5:
                # LLM 文本是实际文本的前缀，且长度至少5个字符，给予高分
                return max(0.85, length_ratio)
            elif norm1.startswith(norm2) and len(norm2) >= 5:
                # 实际文本是 LLM 文本的前缀（较少见），也给予高分
                return max(0.85, length_ratio)
            else:
                # 普通的包含关系，使用长度比例
                return length_ratio
        
        # 策略3：SequenceMatcher
        ratio = SequenceMatcher(None, norm1, norm2).ratio()
        
        # 策略4：关键词重叠（中文分词简化版）
        keywords1 = set(self._extract_keywords(norm1))
        keywords2 = set(self._extract_keywords(norm2))
        
        if keywords1 and keywords2:
            intersection = keywords1 & keywords2
            union = keywords1 | keywords2
            keyword_overlap = len(intersection) / len(union) if union else 0
            
            # 综合打分：序列匹配 60% + 关键词重叠 40%
            return ratio * 0.6 + keyword_overlap * 0.4
        
        return ratio
    
    def _normalize_text(self, text: str) -> str:
        """归一化文本"""
        # 去除多余空格
        text = re.sub(r'\s+', ' ', text).strip()
        # 去除常见的装饰字符
        text = re.sub(r'[【】\[\]()（）《》<>「」『』""\'\'\"\"·•\-—_=+]', '', text)
        # 转小写
        return text.lower()
    
    def _extract_keywords(self, text: str) -> list[str]:
        """提取关键词（简化版，适用于中文）
        
        对于中文，直接按字符切分；对于英文，按单词切分
        """
        keywords = []
        
        # 提取中文词（2-4字的连续中文）
        chinese_pattern = re.compile(r'[\u4e00-\u9fff]{2,4}')
        keywords.extend(chinese_pattern.findall(text))
        
        # 提取英文单词
        english_pattern = re.compile(r'[a-zA-Z]{3,}')
        keywords.extend(english_pattern.findall(text.lower()))
        
        # 提取数字
        number_pattern = re.compile(r'\d{4,}')
        keywords.extend(number_pattern.findall(text))
        
        return keywords


# 兼容旧版本的 mark_ids 列表格式
def convert_mark_ids_to_map(
    mark_ids: list[int],
    snapshot: "SoMSnapshot",
) -> dict[str, str]:
    """将旧版本的 mark_ids 列表转换为 mark_id_text_map 格式
    
    用于向后兼容。自动从 snapshot 中获取每个 mark_id 对应的文本。
    
    Args:
        mark_ids: mark_id 列表
        snapshot: SoM 快照
        
    Returns:
        {mark_id: text} 映射
    """
    mark_id_to_element = {m.mark_id: m for m in snapshot.marks}
    result = {}
    
    for mark_id in mark_ids:
        element = mark_id_to_element.get(mark_id)
        if element:
            result[str(mark_id)] = element.text or ""
    
    return result
