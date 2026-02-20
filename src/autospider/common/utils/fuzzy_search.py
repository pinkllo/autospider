"""HTML 文本模糊搜索工具

用于在 HTML 中定位目标文本，支持模糊匹配和 XPath 生成。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from difflib import SequenceMatcher
from html import unescape
from urllib.parse import parse_qs, urlparse

from lxml import html as lxml_html
from lxml.etree import _Element

if TYPE_CHECKING:
    pass

# 常见的随机/动态 ID 正则：长数字串、UUID、hash 等
_RANDOM_ID_RE = re.compile(
    r"(?:\d{6,}|[0-9a-f]{8,}|[a-z0-9]{20,}|__next|:r\d+:)", re.IGNORECASE
)

# 常见的噪声 class 关键词（布局/状态类，跨页面不稳定）
_NOISE_CLASS_TOKENS = frozenset({
    "active", "hover", "focus", "visited", "selected", "checked",
    "disabled", "hidden", "show", "open", "close", "closed",
    "visible", "invisible", "collapsed", "expanded",
    "fade", "in", "out", "slide",
    "col", "row", "container", "wrapper", "inner", "outer",
    "clearfix", "pull-left", "pull-right",
    "first", "last", "odd", "even",
})


@dataclass
class TextMatch:
    """文本匹配结果"""

    text: str  # 匹配到的文本
    similarity: float  # 相似度 (0-1)
    element_xpath: str  # 包含该文本的元素的 XPath（主 XPath，最稳定的那个）
    element_tag: str  # 元素标签名
    element_text_content: str  # 元素的完整文本内容
    source_attr: str | None = None  # 命中的属性名（如 href/src）
    position: int = 0  # 在页面中的位置索引（用于消歧）
    xpath_candidates: list[dict] = field(default_factory=list)  # 多策略 XPath 候选列表


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
            if not self._is_searchable_element(element):
                continue

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
                if parent is not None and self._is_searchable_element(parent):
                    match = self._check_text_match(
                        parent, element.tail, target_text, threshold, position
                    )
                    if match:
                        matches.append(match)
                position += 1

        # 按相似度降序排列
        matches.sort(key=lambda m: m.similarity, reverse=True)

        return matches

    def search_url_in_html(self, html_content: str, target_url: str) -> list[TextMatch]:
        """
        在 HTML 中按 URL 属性（href/src/data-href/content）搜索目标链接。
        """
        if not target_url or not html_content:
            return []

        try:
            tree = lxml_html.fromstring(html_content)
        except Exception:
            try:
                tree = lxml_html.fragment_fromstring(html_content, create_parent="div")
            except Exception:
                return []

        target_url = unescape(target_url.strip())
        matches: list[TextMatch] = []
        position = 0

        for element in tree.iter():
            if not self._is_searchable_element(element):
                continue

            for attr_name in ("href", "src", "data-href", "content"):
                raw_value = element.get(attr_name)
                if not raw_value:
                    continue
                attr_value = unescape(str(raw_value).strip())
                if not attr_value:
                    continue

                similarity = self._calculate_url_similarity(attr_value, target_url)
                if similarity < 0.7:
                    continue

                candidates = self._generate_xpath_candidates(element)
                best_xpath = candidates[0]["xpath"] if candidates else self._generate_xpath(element)
                if not best_xpath:
                    continue

                matches.append(
                    TextMatch(
                        text=attr_value,
                        similarity=similarity,
                        element_xpath=best_xpath,
                        element_tag=str(element.tag),
                        element_text_content=self._get_full_text(element),
                        source_attr=attr_name,
                        position=position,
                        xpath_candidates=candidates,
                    )
                )
                position += 1

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
            # 生成多策略 XPath 候选
            candidates = self._generate_xpath_candidates(element)
            # 主 XPath 取最稳定（优先级最低=最好）的候选
            best_xpath = candidates[0]["xpath"] if candidates else self._generate_xpath(element)

            return TextMatch(
                text=text,
                similarity=similarity,
                element_xpath=best_xpath,
                element_tag=element.tag,
                element_text_content=self._get_full_text(element),
                source_attr=None,
                position=position,
                xpath_candidates=candidates,
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
        2. 使用最近祖先 id 作为锚点 + 相对路径
        3. 使用绝对结构路径
        """
        # 尝试使用 id
        elem_id = element.get("id")
        if elem_id:
            return f"//*[@id={self._to_xpath_literal(elem_id)}]"

        # 尝试使用最近祖先 id 作为锚点，提升跨页面稳定性
        anchor = element.getparent()
        while anchor is not None and anchor.tag != "html":
            anchor_id = anchor.get("id")
            if anchor_id:
                relative_path = self._build_relative_path(anchor, element)
                anchor_expr = f"//*[@id={self._to_xpath_literal(anchor_id)}]"
                if relative_path:
                    return f"{anchor_expr}/{relative_path}"
                return anchor_expr
            anchor = anchor.getparent()

        # 回退：绝对结构路径
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

    def _generate_xpath_candidates(self, element: _Element) -> list[dict]:
        """为元素生成多策略 XPath 候选列表

        生成策略（按稳定性从高到低）：
        1. @id 精确匹配
        2. @data-testid / @data-test / @data-qa 等测试属性
        3. 祖先 @id 锚点 + 相对路径
        4. 祖先 @id 锚点 + class 增强的相对路径
        5. @class 属性锚点路径
        6. @data-* 属性锚点路径
        7. 传统绝对结构路径（回退）

        Returns:
            候选列表，每项包含 xpath, priority, strategy
        """
        candidates: list[dict] = []
        seen_xpaths: set[str] = set()

        def _add(xpath: str, priority: int, strategy: str) -> None:
            if xpath and xpath not in seen_xpaths:
                seen_xpaths.add(xpath)
                candidates.append({"xpath": xpath, "priority": priority, "strategy": strategy})

        # --- 策略 1: 自身 @id ---
        elem_id = element.get("id")
        if elem_id and not _RANDOM_ID_RE.search(elem_id):
            _add(f"//*[@id={self._to_xpath_literal(elem_id)}]", 1, "id")

        # --- 策略 2: 测试属性 ---
        for attr in ("data-testid", "data-test", "data-qa", "data-cy"):
            val = element.get(attr)
            if val:
                _add(f"//*[@{attr}={self._to_xpath_literal(val)}]", 2, "testid")

        # --- 策略 3/4: 祖先 @id 锚点 ---
        anchor = element.getparent()
        while anchor is not None and anchor.tag != "html":
            anchor_id = anchor.get("id")
            if anchor_id and not _RANDOM_ID_RE.search(anchor_id):
                anchor_expr = f"//*[@id={self._to_xpath_literal(anchor_id)}]"
                # 3a: 纯结构相对路径
                relative_path = self._build_relative_path(anchor, element)
                if relative_path:
                    _add(f"{anchor_expr}/{relative_path}", 3, "id-relative")
                # 3b: class 增强的相对路径 (已被废弃，不再使用，会产生极长且包含冗余外观样式的XPath)
                # class_relative = self._build_class_anchored_relative(anchor, element)
                # if class_relative:
                #     _add(f"{anchor_expr}/{class_relative}", 4, "id-class-relative")
                break
            anchor = anchor.getparent()

        # --- 策略 5: class 属性锚点（从元素本身或近祖先寻找稳定 class）---
        class_xpath = self._build_class_anchored_xpath(element)
        if class_xpath:
            _add(class_xpath, 5, "class-anchor")

        # --- 策略 6: data-* 属性锚点 ---
        data_xpath = self._build_data_attr_xpath(element)
        if data_xpath:
            _add(data_xpath, 6, "data-attr")

        # --- 策略 7: 传统绝对路径（回退） ---
        fallback = self._generate_xpath(element)
        if fallback:
            _add(fallback, 7, "absolute")

        candidates.sort(key=lambda c: c["priority"])
        return candidates

    def _get_stable_classes(self, element: _Element) -> list[str]:
        """获取元素上稳定的 CSS class 列表（过滤掉噪声 class）"""
        raw = (element.get("class") or "").strip()
        if not raw:
            return []
        classes = []
        for cls in raw.split():
            cls = cls.strip()
            if not cls:
                continue
            # 过滤纯数字、过短、噪声 token
            if len(cls) < 3:
                continue
            if cls.isdigit():
                continue
            if cls.lower() in _NOISE_CLASS_TOKENS:
                continue
            # 过滤含长数字串的动态 class（如 css-1a2b3c4）
            if _RANDOM_ID_RE.search(cls):
                continue
            classes.append(cls)
        return classes

    def _build_class_anchored_xpath(self, element: _Element) -> str | None:
        """基于 class 属性构建锚定 XPath

        策略：
        - 优先用元素自身的稳定 class
        - 若元素自身没有稳定 class，向上找最近有稳定 class 的祖先，
          然后拼接从该祖先到目标元素的结构路径
        """
        tag = str(element.tag)

        # 自身有稳定 class
        stable_classes = self._get_stable_classes(element)
        if stable_classes:
            cls = stable_classes[0]
            return f"//{tag}[contains(@class, {self._to_xpath_literal(cls)})]"

        # 向上找有稳定 class 的祖先
        current = element.getparent()
        depth = 0
        while current is not None and current.tag != "html" and depth < 6:
            ancestor_classes = self._get_stable_classes(current)
            if ancestor_classes:
                cls = ancestor_classes[0]
                ancestor_tag = str(current.tag)
                anchor_expr = f"//{ancestor_tag}[contains(@class, {self._to_xpath_literal(cls)})]"
                relative = self._build_relative_path(current, element)
                if relative:
                    return f"{anchor_expr}/{relative}"
            current = current.getparent()
            depth += 1

        return None

    def _build_data_attr_xpath(self, element: _Element) -> str | None:
        """基于 data-* 属性构建锚定 XPath"""
        tag = str(element.tag)
        for attr_name in element.attrib:
            if not attr_name.startswith("data-"):
                continue
            # 跳过测试属性（已在策略 2 处理）
            if attr_name in ("data-testid", "data-test", "data-qa", "data-cy"):
                continue
            val = element.get(attr_name)
            if val and len(val) < 80 and not _RANDOM_ID_RE.search(val):
                return f"//{tag}[@{attr_name}={self._to_xpath_literal(val)}]"
        return None

    # def _build_class_anchored_relative(
    #     self, anchor: _Element, element: _Element
    # ) -> str | None:
    #     """构建基于 class 增强的相对路径
    # 
    #     在从 anchor 到 element 的路径中，如果中间某个节点有稳定 class，
    #     用 class 断点替换数字索引，提升跨页面稳定性。
    #     """
    #     segments: list[str] = []
    #     current = element
    # 
    #     while current is not None and current is not anchor:
    #         parent = current.getparent()
    #         if parent is None:
    #             return None
    # 
    #         tag = str(current.tag)
    #         stable_classes = self._get_stable_classes(current)
    # 
    #         if stable_classes:
    #             cls = stable_classes[0]
    #             same_class_siblings = []
    #             for child in parent:
    #                 if child.tag == current.tag:
    #                     child_classes = self._get_stable_classes(child)
    #                     if cls in child_classes:
    #                         same_class_siblings.append(child)
    #             
    #             if len(same_class_siblings) > 1:
    #                 index = same_class_siblings.index(current) + 1
    #                 segments.append(f"{tag}[contains(@class, {self._to_xpath_literal(cls)})][{index}]")
    #             else:
    #                 segments.append(f"{tag}[contains(@class, {self._to_xpath_literal(cls)})]")
    #         else:
    #             siblings = [child for child in parent if child.tag == current.tag]
    #             if len(siblings) > 1:
    #                 index = siblings.index(current) + 1
    #                 segments.append(f"{tag}[{index}]")
    #             else:
    #                 segments.append(tag)
    # 
    #         current = parent
    # 
    #     if current is not anchor:
    #         return None
    # 
    #     segments.reverse()
    #     result = "/".join(segments)
    # 
    #     # 如果和纯结构路径完全相同，说明没有 class 增强效果
    #     plain = self._build_relative_path(anchor, element)
    #     if result == plain:
    #         return None
    # 
    #     return result

    def _is_searchable_element(self, element: _Element) -> bool:
        """过滤无效标签与噪声节点，减少误匹配。"""
        tag = getattr(element, "tag", None)
        if not isinstance(tag, str):
            return False
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "template"}:
            return False
        return True

    def _calculate_url_similarity(self, candidate_url: str, target_url: str) -> float:
        """计算 URL 相似度（优先结构化比较）。"""
        c = candidate_url.strip()
        t = target_url.strip()
        if not c or not t:
            return 0.0
        if c == t:
            return 1.0

        c_norm = self._normalize_url(c)
        t_norm = self._normalize_url(t)
        if c_norm and t_norm and c_norm == t_norm:
            return 0.98

        c_path = self._url_path_and_id(c)
        t_path = self._url_path_and_id(t)
        if c_path and t_path and c_path == t_path:
            return 0.95

        c_lower = c.lower()
        t_lower = t.lower()
        if c_lower in t_lower or t_lower in c_lower:
            return 0.9

        return SequenceMatcher(None, c_lower, t_lower).ratio()

    def _normalize_url(self, url: str) -> tuple | None:
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return None
            query = parse_qs(parsed.query, keep_blank_values=True)
            query_norm = tuple(
                sorted((k, tuple(sorted(v))) for k, v in query.items())
            )
            return (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path,
                query_norm,
            )
        except Exception:
            return None

    def _url_path_and_id(self, url: str) -> tuple[str, str | None] | None:
        try:
            parsed = urlparse(url)
            if not parsed.path:
                return None
            query = parse_qs(parsed.query, keep_blank_values=True)
            id_value = (query.get("id") or [None])[0]
            return parsed.path, id_value
        except Exception:
            return None

    def _build_relative_path(self, anchor: _Element, element: _Element) -> str:
        """构建从锚点到目标元素的相对路径（不含锚点自身）"""
        segments: list[str] = []
        current = element

        while current is not None and current is not anchor:
            parent = current.getparent()
            if parent is None:
                return ""

            siblings = [child for child in parent if child.tag == current.tag]
            if len(siblings) > 1:
                index = siblings.index(current) + 1
                segments.append(f"{current.tag}[{index}]")
            else:
                segments.append(str(current.tag))

            current = parent

        if current is not anchor:
            return ""

        segments.reverse()
        return "/".join(segments)

    def _to_xpath_literal(self, value: str) -> str:
        """将任意字符串安全地转换为 XPath 字面量"""
        if '"' not in value:
            return f'"{value}"'
        if "'" not in value:
            return f"'{value}'"

        parts = value.split('"')
        quoted_parts = [f'"{part}"' for part in parts]
        return 'concat(' + ", '\"', ".join(quoted_parts) + ")"

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
