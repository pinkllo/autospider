"""URL 收集器数据模型定义"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DetailPageVisit:
    """一次详情页访问记录"""

    # 入口信息
    list_page_url: str  # 列表页 URL
    detail_page_url: str  # 详情页 URL

    # 点击的元素信息
    clicked_element_mark_id: int
    clicked_element_tag: str
    clicked_element_text: str
    clicked_element_href: str | None
    clicked_element_role: str | None
    clicked_element_xpath_candidates: list[dict]

    # 上下文
    step_index: int
    timestamp: str


@dataclass
class CommonPattern:
    """从多次访问中提取的公共模式"""

    # 元素选择器模式
    tag_pattern: str | None = None  # 如 "a", "div" 等
    role_pattern: str | None = None  # 如 "link", "button" 等
    text_pattern: str | None = None  # 正则表达式匹配文本
    href_pattern: str | None = None  # 正则表达式匹配链接

    # XPath 模式
    common_xpath_prefix: str | None = None  # 公共 XPath 前缀
    xpath_pattern: str | None = None  # XPath 模式

    # 置信度
    confidence: float = 0.0

    # 原始访问记录
    source_visits: list[DetailPageVisit] = field(default_factory=list)


@dataclass
class URLCollectorResult:
    """URL 收集结果"""

    # 探索阶段
    detail_visits: list[DetailPageVisit] = field(default_factory=list)

    # 分析阶段
    common_pattern: CommonPattern | None = None

    # 收集阶段
    collected_urls: list[str] = field(default_factory=list)

    # 元信息
    list_page_url: str = ""
    task_description: str = ""  # 任务描述
    total_pages_scrolled: int = 0
    created_at: str = ""
