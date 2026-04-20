"""Planning infrastructure adapter that assembles the runtime TaskPlanner."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_openai import ChatOpenAI

from autospider.platform.config.runtime import config
from autospider.platform.observability.logger import get_logger
from autospider.contexts.planning.application.use_cases.control_payloads import (
    build_planner_control_payload,
    build_planner_world_payload,
)
from autospider.contexts.collection.domain.variant_resolver import PlannerVariantResolverMixin
from autospider.contexts.planning.domain import PlannerIntent
from autospider.contexts.planning.infrastructure.adapters.analysis_support import (
    PlannerAnalysisSupportMixin,
    ResolvedPlannerVariant,
    RuntimeSubtaskPlanResult,
)
from autospider.contexts.planning.infrastructure.adapters.entry_planning import (
    PlannerEntryPlanningMixin,
)
from autospider.contexts.planning.infrastructure.adapters.page_runtime import (
    PlannerPageRuntimeMixin,
)
from autospider.contexts.planning.infrastructure.adapters.plan_records import (
    PlannerPlanRecordsMixin,
)
from autospider.contexts.planning.application.use_cases.analyze_plan_result import (
    PlannerAnalysisPostProcessMixin,
)
from autospider.contexts.planning.domain.page_state import PlannerPageState
from autospider.contexts.planning.domain.services import (
    PlannerCategorySemanticsMixin,
    PlannerSubtaskBuilderMixin,
)
from autospider.contexts.planning.infrastructure.repositories.artifact_store import (
    ArtifactPlanRepository,
)

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = get_logger(__name__)


PlannerVariantResolverMixin.ResolvedPlannerVariant = ResolvedPlannerVariant
__all__ = [
    "ResolvedPlannerVariant",
    "RuntimeSubtaskPlanResult",
    "TaskPlanner",
    "build_planner_control_payload",
    "build_planner_world_payload",
]


class TaskPlanner(
    PlannerEntryPlanningMixin,
    PlannerPageRuntimeMixin,
    PlannerPlanRecordsMixin,
    PlannerAnalysisSupportMixin,
    PlannerCategorySemanticsMixin,
    PlannerAnalysisPostProcessMixin,
    PlannerSubtaskBuilderMixin,
    PlannerVariantResolverMixin,
):
    """任务规划器：负责将用户的采集请求转化为具体的执行计划。

    主要功能包括：
    1. 导航至目标站点。
    2. 利用 SoM (Set-of-Mark) 技术对页面元素进行标注并截图。
    3. 调用具备视觉能力的 LLM 分析页面结构，识别出符合用户需求的分类入口。
    4. 针对不同类型的网页（静态/SPA），采用多种策略提取分类的实际跳转 URL。
    5. 构建并持久化任务计划 (TaskPlan)，供后续 Worker Agent 执行。
    """

    def __init__(
        self,
        page: "Page",
        site_url: str,
        user_request: str,
        output_dir: str = "output",
        use_main_model: bool = False,
        selected_skills_context: str = "",
        selected_skills: list[dict] | None = None,
        planner_intent: PlannerIntent | dict[str, Any] | None = None,
        prior_failures: list[dict[str, Any]] | None = None,
    ):
        """初始化任务规划器。

        Args:
            page: Playwright 页面实例，用于浏览器交互。
            site_url: 目标网站的根地址或起始 URL。
            user_request: 用户的原始采集需求描述。
            output_dir: 规划结果（TaskPlan）的保存目录，默认为 "output"。
            use_main_model: 是否强制使用主模型配置（用于执行阶段权限下放）。
            prior_failures: 上一轮调度累积的 FailureRecord 列表，用于 replan 时告知 LLM 需要规避哪些策略。
        """
        self.page = page
        self.site_url = site_url
        self.user_request = user_request
        self.output_dir = output_dir
        self.selected_skills_context = str(selected_skills_context or "")
        self.selected_skills = list(selected_skills or [])
        self.prior_failures = [dict(item) for item in list(prior_failures or [])]
        self.planner_intent = (
            planner_intent
            if isinstance(planner_intent, PlannerIntent)
            else PlannerIntent.from_payload(planner_intent)
        )
        self._knowledge_entries: list[dict] = []  # 规划发现过程中收集的知识条目
        self._journal_entries: list[dict] = []
        self._sibling_category_registry: dict[str, set[str]] = {}
        self._page_state = PlannerPageState(page)
        self._artifacts = ArtifactPlanRepository(
            site_url=site_url,
            user_request=user_request,
            output_dir=output_dir,
        )
        self.planner_status = "success"
        self.terminal_reason = ""

        if use_main_model:
            api_key = config.llm.api_key
            api_base = config.llm.api_base
            model = config.llm.model
        else:
            api_key = config.llm.planner_api_key or config.llm.api_key
            api_base = config.llm.planner_api_base or config.llm.api_base
            model = config.llm.planner_model or config.llm.model

        # 初始化 ChatOpenAI 实例
        self.llm = ChatOpenAI(
            api_key=api_key,
            base_url=api_base,
            model=model,
            temperature=config.llm.temperature,
            max_tokens=config.llm.max_tokens,
            model_kwargs={"response_format": {"type": "json_object"}},
            extra_body={"enable_thinking": config.llm.enable_thinking},
        )
