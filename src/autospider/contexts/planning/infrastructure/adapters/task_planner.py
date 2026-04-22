"""Planning infrastructure adapter that assembles the runtime TaskPlanner."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from autospider.platform.config.runtime import config
from autospider.platform.llm.client_factory import build_runtime_json_llm
from autospider.platform.observability.logger import get_logger
from autospider.contexts.collection import NavigationHandler
from autospider.contexts.planning.domain import PlannerIntent, TaskPlan
from autospider.contexts.planning.infrastructure.adapters.analysis_support import (
    PlannerSiteAnalyzer,
    ResolvedPlannerVariant,
    RuntimeSubtaskPlanResult,
)
from autospider.contexts.planning.infrastructure.adapters.entry_planning import (
    PlannerEntryPlanner,
)
from autospider.contexts.planning.infrastructure.adapters.page_runtime import (
    PlannerPageRuntimeMixin,
)
from autospider.contexts.planning.infrastructure.adapters.plan_records import (
    PlannerPlanRecordBook,
)
from autospider.contexts.planning.infrastructure.adapters.variant_resolution import (
    PlannerVariantResolverMixin,
)
from autospider.contexts.planning.application.use_cases.analyze_plan_result import (
    PlannerAnalysisPostProcessor,
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
]


def _build_planner_navigation_replayer(
    *,
    page: "Page",
    target_url: str,
    max_nav_steps: int,
) -> NavigationHandler:
    return NavigationHandler(page, target_url, "", max_nav_steps)


class TaskPlanner(
    PlannerPageRuntimeMixin,
    PlannerCategorySemanticsMixin,
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
        self._sibling_category_registry: dict[str, set[str]] = {}
        self._page_state = PlannerPageState(
            page,
            navigation_replayer_factory=_build_planner_navigation_replayer,
        )
        self._plan_records = PlannerPlanRecordBook(
            artifacts=ArtifactPlanRepository(
                site_url=site_url,
                user_request=user_request,
                output_dir=output_dir,
            )
        )
        self._analysis_post_processor = PlannerAnalysisPostProcessor(self)
        self._site_analyzer = PlannerSiteAnalyzer(self)
        self._entry_planner = PlannerEntryPlanner(self)
        self.planner_status = "success"
        self.terminal_reason = ""

        if use_main_model:
            prefer_planner = False
        else:
            prefer_planner = True

        self.llm = build_runtime_json_llm(
            prefer_planner=prefer_planner,
            temperature=config.llm.temperature,
            max_tokens=config.llm.max_tokens,
            use_main_model=use_main_model,
        )

    async def plan(self) -> TaskPlan:
        return await self._entry_planner.plan()

    def _get_site_analyzer(self) -> PlannerSiteAnalyzer:
        analyzer = getattr(self, "_site_analyzer", None)
        if analyzer is None:
            analyzer = PlannerSiteAnalyzer(self)
            self._site_analyzer = analyzer
        return analyzer

    def _get_analysis_post_processor(self) -> PlannerAnalysisPostProcessor:
        processor = getattr(self, "_analysis_post_processor", None)
        if processor is None:
            processor = PlannerAnalysisPostProcessor(self)
            self._analysis_post_processor = processor
        return processor

    def _append_observation_note(self, result: dict, note: str) -> dict:
        return self._get_site_analyzer()._append_observation_note(result, note)

    def _get_grouping_semantics(self) -> dict[str, Any]:
        return self._get_site_analyzer()._get_grouping_semantics()

    def _format_prior_failures(self, *, limit: int = 5) -> str:
        return self._get_site_analyzer()._format_prior_failures(limit=limit)

    async def _analyze_site_structure(
        self,
        screenshot_base64: str,
        snapshot: object,
        *,
        node_context: dict[str, str] | None = None,
        nav_steps: list[dict] | None = None,
    ) -> dict | None:
        return await self._get_site_analyzer()._analyze_site_structure(
            screenshot_base64,
            snapshot,
            node_context=node_context,
            nav_steps=nav_steps,
        )

    def _post_process_analysis(
        self,
        result: dict,
        snapshot: object,
        *,
        node_context: dict[str, str] | None = None,
    ) -> dict:
        return self._get_analysis_post_processor()._post_process_analysis(
            result,
            snapshot,
            node_context=node_context,
        )

    def _looks_like_current_category(self, name: str, analysis: dict) -> bool:
        return self._get_analysis_post_processor()._looks_like_current_category(
            name,
            analysis,
        )

    def render_plan_knowledge(self, plan) -> str:
        return self._plan_records.render_plan_knowledge(plan)
