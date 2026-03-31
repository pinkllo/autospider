"""Spider Skill 数据模型。

定义站点经验的结构化表示，用于在 YAML frontmatter 中存储
可精确复用的硬指标（XPath、导航步骤等）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass
class FieldExperience:
    """单个字段的提取经验。"""

    field_name: str
    original_description: str = ""
    primary_xpath: str | None = None
    fallback_xpaths: list[str] = field(default_factory=list)
    confidence: float = 0.0
    validated: bool = False
    data_type: str = "text"
    extraction_source: str | None = None
    fixed_value: str | None = None


@dataclass
class NavStepExperience:
    """单步导航经验。"""

    action: str = ""
    xpath: str | None = None
    value: str | None = None
    description: str = ""


@dataclass
class SiteSkill:
    """站点级 Spider Skill — 一个域名/URL 模式的完整经验档案。

    包含两部分：
    - 结构化硬数据（YAML frontmatter）：可直接被代码解析和复用
    - 自然语言软经验（Markdown 正文）：供 LLM 阅读理解
    """

    # --- 站点标识 ---
    domain: str = ""
    list_url: str = ""
    url_pattern: str = ""
    task_description: str = ""

    # --- 导航配方 ---
    nav_steps: list[NavStepExperience] = field(default_factory=list)

    # --- 链接提取 ---
    detail_link_xpath: str | None = None
    pagination_xpath: str | None = None
    jump_widget_xpath: dict[str, str] | None = None

    # --- 字段提取经验 ---
    fields_experience: list[FieldExperience] = field(default_factory=list)

    # --- 元信息 ---
    status: str = "validated"  # validated / stale / draft
    confidence: float = 0.0
    total_executions: int = 0
    total_urls_processed: int = 0
    success_rate: float = 0.0
    created_at: str = ""
    updated_at: str = ""

    # --- 软经验（LLM 生成的 Markdown 文本） ---
    insights_markdown: str = ""

    # --- 子任务聚合信息 ---
    subtask_count: int = 0
    subtask_names: list[str] = field(default_factory=list)

    def to_frontmatter_dict(self) -> dict:
        """仅导出结构化硬数据（用于 YAML frontmatter），不含 Markdown 正文。"""
        data = asdict(self)
        data.pop("insights_markdown", None)
        # 清理空值
        return {k: v for k, v in data.items() if v is not None and v != "" and v != []}

    def touch(self) -> None:
        """刷新 updated_at 时间戳。"""
        self.updated_at = datetime.now().isoformat()
        if not self.created_at:
            self.created_at = self.updated_at
