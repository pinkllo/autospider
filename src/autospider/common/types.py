"""核心数据类型定义"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# ============================================================================
# 输入参数
# ============================================================================


class RunInput(BaseModel):
    """Agent 运行输入参数"""

    start_url: str = Field(..., description="起始 URL")
    task: str = Field(..., description="任务描述（自然语言）")
    target_text: str = Field(..., description="提取目标文本")
    max_steps: int = Field(default=20, description="最大执行步数")
    headless: bool = Field(default=False, description="无头模式")
    output_dir: str = Field(default="output", description="输出目录")


# ============================================================================
# SoM 标注相关
# ============================================================================


class BoundingBox(BaseModel):
    """元素边界框（视口坐标）"""

    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> tuple[float, float]:
        """返回归一化中心坐标（用于 LLM 辅助校验）"""
        return (self.x + self.width / 2, self.y + self.height / 2)


class XPathCandidate(BaseModel):
    """XPath 候选项（按稳定性排序）"""

    xpath: str = Field(..., description="XPath 表达式")
    priority: int = Field(..., description="优先级：1=最稳定, 5=最脆弱")
    strategy: str = Field(..., description="生成策略：id/testid/aria/text/relative")
    confidence: float = Field(default=1.0, description="唯一性置信度")


class ElementMark(BaseModel):
    """SoM 标注的元素"""

    mark_id: int = Field(..., description="数字编号（截图上显示）")
    tag: str = Field(..., description="HTML 标签名")
    role: str | None = Field(default=None, description="ARIA role")
    text: str = Field(default="", description="可见文本（截断）")
    aria_label: str | None = Field(default=None, description="aria-label")
    placeholder: str | None = Field(default=None, description="placeholder")
    href: str | None = Field(default=None, description="链接地址")
    input_type: str | None = Field(default=None, description="input 类型")
    clickability_reason: str | None = Field(default=None, description="可点击性判定依据")
    clickability_confidence: float | None = Field(default=None, description="可点击性置信度")
    bbox: BoundingBox = Field(..., description="边界框")
    center_normalized: tuple[float, float] = Field(..., description="归一化中心坐标 (0-1)")
    xpath_candidates: list[XPathCandidate] = Field(
        default_factory=list, description="XPath 候选列表（按稳定性排序）"
    )
    is_visible: bool = Field(default=True, description="是否可见（未被遮挡）")
    z_index: int = Field(default=0, description="Z 轴层级")


class ScrollInfo(BaseModel):
    """页面滚动状态信息"""

    scroll_top: int = Field(default=0, description="当前滚动位置（像素）")
    scroll_height: int = Field(default=0, description="页面总高度（像素）")
    client_height: int = Field(default=0, description="可视区域高度（像素）")
    scroll_percent: int = Field(default=0, description="滚动百分比 0-100")
    is_at_top: bool = Field(default=True, description="是否在页面顶部")
    is_at_bottom: bool = Field(default=False, description="是否在页面底部")
    can_scroll_down: bool = Field(default=True, description="是否可以向下滚动")
    can_scroll_up: bool = Field(default=False, description="是否可以向上滚动")


class SoMSnapshot(BaseModel):
    """SoM 快照（一次观察的完整结果）"""

    url: str
    title: str
    viewport_width: int
    viewport_height: int
    marks: list[ElementMark]
    screenshot_base64: str = Field(default="", description="带标注的截图（Base64）")
    timestamp: float
    scroll_info: ScrollInfo | None = Field(default=None, description="页面滚动状态")


# ============================================================================
# 动作定义
# ============================================================================


class ActionType(str, Enum):
    """动作类型枚举"""

    CLICK = "click"
    TYPE = "type"
    PRESS = "press"
    SCROLL = "scroll"
    NAVIGATE = "navigate"
    WAIT = "wait"
    EXTRACT = "extract"
    GO_BACK = "go_back"  # 返回当前标签页上一页
    GO_BACK_TAB = "go_back_tab"  # 返回上一标签页
    DONE = "done"
    RETRY = "retry"


class Action(BaseModel):
    """LLM 输出的动作"""

    action: ActionType = Field(..., description="动作类型")
    mark_id: int | None = Field(default=None, description="目标元素编号")
    target_text: str | None = Field(default=None, description="目标文本（用于校验）")
    text: str | None = Field(default=None, description="输入文本（type 动作）")
    key: str | None = Field(default=None, description="按键（press 动作）")
    url: str | None = Field(default=None, description="导航 URL")
    scroll_delta: tuple[int, int] | None = Field(default=None, description="滚动量 (dx, dy)")
    timeout_ms: int = Field(default=5000, description="等待超时")
    thinking: str = Field(default="", description="LLM 决策推理过程")
    expectation: str | None = Field(default=None, description="预期结果（用于校验）")


class ActionResult(BaseModel):
    """动作执行结果"""

    success: bool
    error: str | None = None
    new_url: str | None = None
    extracted_text: str | None = None
    screenshot_path: str | None = None


# ============================================================================
# XPath 脚本步骤（最终输出）
# ============================================================================


class ScriptStepType(str, Enum):
    """脚本步骤类型"""

    CLICK = "click"
    TYPE = "type"
    PRESS = "press"
    SCROLL = "scroll"
    NAVIGATE = "navigate"
    WAIT = "wait"
    EXTRACT = "extract"


class ScriptStep(BaseModel):
    """XPath 脚本步骤（可复用）"""

    step: int = Field(..., description="步骤序号")
    action: ScriptStepType
    target_xpath: str | None = Field(default=None, description="目标元素 XPath")
    xpath_alternatives: list[str] = Field(
        default_factory=list, description="备选 XPath 列表（按稳定性排序）"
    )
    value: str | None = Field(default=None, description="输入值（支持 ${VAR} 占位符）")
    key: str | None = Field(default=None, description="按键")
    url: str | None = Field(default=None, description="导航 URL")
    scroll_delta: tuple[int, int] | None = Field(default=None, description="滚动量")
    wait_condition: str | None = Field(default=None, description="等待条件")
    timeout_ms: int = Field(default=5000, description="超时时间")
    description: str = Field(default="", description="步骤描述")
    screenshot_context: str | None = Field(default=None, description="截图路径（调试用）")


class XPathScript(BaseModel):
    """完整的 XPath 脚本"""

    task: str = Field(..., description="原始任务描述")
    start_url: str = Field(..., description="起始 URL")
    target_text: str = Field(..., description="提取目标")
    steps: list[ScriptStep] = Field(default_factory=list)
    extracted_result: str | None = Field(default=None, description="最终提取结果")
    variables: dict[str, str] = Field(default_factory=dict, description="变量定义（用于参数化）")
    created_at: str = Field(default="", description="创建时间")


# ============================================================================
# LangGraph 状态
# ============================================================================


class AgentState(BaseModel):
    """LangGraph Agent 状态"""

    # 输入
    input: RunInput

    # 当前状态
    step_index: int = Field(default=0)
    page_url: str = Field(default="")
    page_title: str = Field(default="")

    # 观察结果
    current_snapshot: SoMSnapshot | None = None
    mark_id_to_xpath: dict[int, list[str]] = Field(
        default_factory=dict, description="mark_id -> xpath 列表映射"
    )

    # 动作历史
    last_action: Action | None = None
    last_result: ActionResult | None = None
    action_history: list[tuple[Action, ActionResult]] = Field(default_factory=list)

    # 脚本沉淀
    script_steps: list[ScriptStep] = Field(default_factory=list)

    # 状态标志
    done: bool = Field(default=False)
    success: bool = Field(default=False)
    error: str | None = None
    fail_count: int = Field(default=0)
    max_fail_count: int = Field(default=3)

    class Config:
        arbitrary_types_allowed = True
