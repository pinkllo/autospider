"""任务规划器 (Task Planner) — 负责分析网站结构并将复杂的采集任务拆分为多个子任务。

该模块的核心逻辑是通过 LLM (语言模型) 结合视觉分析 (结合 SoM 标注的截图)，识别目标网站的导航结构
（如菜单、分类列表、频道入口等），并自动生成一系列独立的子任务。
每个子任务通常对应一个特定的分类或频道的列表页。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ...common.config import config
from ...common.logger import get_logger
from ...common.protocol import parse_json_dict_from_llm
from ...common.som import inject_and_scan, capture_screenshot_with_marks, clear_overlay
from ...common.som.text_first import resolve_single_mark_id
from ...domain.planning import (
    ExecutionBrief,
    PlanJournalEntry,
    PlanNode,
    PlanNodeType,
    SubTask,
    SubTaskMode,
    TaskPlan,
)
from ...common.utils.paths import get_prompt_path
from ...common.utils.prompt_template import render_template
from .planner_artifacts import PlannerArtifacts
from .planner_state import PlannerPageState

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = get_logger(__name__)

PROMPT_TEMPLATE_PATH = get_prompt_path("planner.yaml")
CATEGORY_PATH_KEY = "category_path"
CATEGORY_PATH_SEPARATOR = " > "
PLANNER_ACTION_HISTORY_LIMIT = 6
SEMANTIC_CATEGORY_SUFFIXES = (
    "分类采集",
    "分类入口",
    "分类导航",
    "分类",
    "采集",
)




@dataclass
class ResolvedPlannerVariant:
    resolved_url: str
    anchor_url: str
    nav_steps: list[dict] = field(default_factory=list)
    page_state_signature: str = ""
    variant_label: str = ""
    context: dict[str, str] = field(default_factory=dict)
    same_page_variant: bool = False


@dataclass
class RuntimeSubtaskPlanResult:
    page_type: str
    analysis: dict[str, Any]
    children: list[SubTask] = field(default_factory=list)
    collect_task_description: str = ""
    collect_execution_brief: ExecutionBrief = field(default_factory=ExecutionBrief)


class TaskPlanner:
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
    ):
        """初始化任务规划器。

        Args:
            page: Playwright 页面实例，用于浏览器交互。
            site_url: 目标网站的根地址或起始 URL。
            user_request: 用户的原始采集需求描述。
            output_dir: 规划结果（TaskPlan）的保存目录，默认为 "output"。
            use_main_model: 是否强制使用主模型配置（用于执行阶段权限下放）。
        """
        self.page = page
        self.site_url = site_url
        self.user_request = user_request
        self.output_dir = output_dir
        self.selected_skills_context = str(selected_skills_context or "")
        self.selected_skills = list(selected_skills or [])
        self._knowledge_entries: list[dict] = []  # 规划发现过程中收集的知识条目
        self._journal_entries: list[dict] = []
        self._sibling_category_registry: dict[str, set[str]] = {}
        self._page_state = PlannerPageState(page)
        self._artifacts = PlannerArtifacts(
            site_url=site_url,
            user_request=user_request,
            output_dir=output_dir,
        )

        # 获取 LLM 配置：
        # - 默认优先使用 planner 专用配置（兼容现有逻辑）
        # - use_main_model=True 时，强制使用主模型，支持“执行阶段下放规划权限”
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

    async def plan(self) -> TaskPlan:
        """只为入口页面生成首层子任务。"""
        logger.info("[Planner] 开始首层任务规划: %s", self.site_url)

        await self.page.goto(self.site_url, wait_until="domcontentloaded", timeout=30000)
        await self.page.wait_for_timeout(2000)
        logger.info("[Planner] 页面已加载: %s", self.page.url)

        subtasks = await self._plan_entry_subtasks()
        plan = self._build_plan(subtasks)
        plan = self._save_plan(plan)
        self._write_knowledge_doc(plan)
        self._sediment_draft_skill(plan)

        logger.info("[Planner] 首层规划完成，发现 %d 个一级任务", len(plan.subtasks))
        return plan

    async def _plan_entry_subtasks(self) -> list[SubTask]:
        current_url = self.page.url
        current_context: dict[str, str] = {}
        current_nav_steps: list[dict] = []
        snapshot = await inject_and_scan(self.page)
        _, screenshot_base64 = await capture_screenshot_with_marks(self.page)
        await clear_overlay(self.page)

        analysis = await self._analyze_site_structure(
            screenshot_base64,
            snapshot,
            node_context=current_context,
            nav_steps=current_nav_steps,
        )
        if not analysis:
            logger.warning("[Planner] 入口页面分析失败")
            return []

        page_type = str(analysis.get("page_type", "category")).strip().lower()
        node_name = str(analysis.get("name", "")).strip() or "入口页面"
        observations = str(analysis.get("observations", "")).strip()
        node_id = self._next_node_id()
        state_signature = self._build_page_state_signature(current_url, current_nav_steps)
        node_type = self._resolve_plan_node_type_for_state(page_type, current_nav_steps)

        entry_index = len(self._knowledge_entries)
        self._knowledge_entries.append({
            "node_id": node_id,
            "parent_node_id": None,
            "depth": 0,
            "url": current_url,
            "anchor_url": current_url,
            "page_state_signature": state_signature,
            "variant_label": None,
            "page_type": page_type,
            "name": node_name,
            "observations": observations,
            "children_count": 0,
            "is_leaf": False,
            "task_description": str(analysis.get("task_description", self.user_request) or self.user_request),
            "context": {},
            "nav_steps": [],
            "subtask_id": None,
            "executable": False,
            "node_type": node_type.value,
        })
        self._append_journal(
            node_id=node_id,
            phase="planning",
            action="analyze_page",
            reason=f"入口页面识别为 {page_type}",
            evidence=observations,
            metadata={"url": current_url, "depth": "0"},
        )

        if page_type == "list_page":
            collect_desc = str(analysis.get("task_description") or "").strip() or self._build_collect_task_description(current_context)
            collect_brief = self._build_collect_execution_brief(current_context, task_description=collect_desc)
            subtask = SubTask(
                id="leaf_001",
                name=node_name,
                list_url=current_url,
                anchor_url=current_url,
                page_state_signature=state_signature,
                task_description=collect_desc,
                nav_steps=[],
                depth=0,
                priority=0,
                context=current_context,
                plan_node_id=node_id,
                mode=SubTaskMode.COLLECT,
                execution_brief=collect_brief,
            )
            self._knowledge_entries[entry_index]["is_leaf"] = True
            self._knowledge_entries[entry_index]["executable"] = True
            self._knowledge_entries[entry_index]["subtask_id"] = subtask.id
            self._append_journal(
                node_id=node_id,
                phase="planning",
                action="register_leaf_subtask",
                reason="入口页面可直接采集，生成 collect 任务",
                evidence=collect_desc,
                metadata={"subtask_id": subtask.id, "mode": subtask.mode.value},
            )
            return [subtask]

        raw_children = list(analysis.get("subtasks") or [])
        if not raw_children:
            self._record_planning_dead_end(
                entry_index=entry_index,
                node_id=node_id,
                reason="入口分类页未识别出首层子分类",
                evidence=observations or self.user_request,
                metadata={"url": current_url, "depth": "0"},
            )
            return []

        child_variants = await self._extract_subtask_variants(
            analysis,
            snapshot,
            current_nav_steps,
            parent_context=current_context,
        )
        if not child_variants:
            self._record_planning_dead_end(
                entry_index=entry_index,
                node_id=node_id,
                reason="入口分类页未生成有效状态任务",
                evidence=self.user_request,
                metadata={"url": current_url, "depth": "0"},
            )
            return []

        subtasks = self._build_subtasks_from_variants(
            child_variants,
            analysis=analysis,
            depth=0,
            mode=SubTaskMode.EXPAND,
        )
        if not subtasks:
            self._record_planning_dead_end(
                entry_index=entry_index,
                node_id=node_id,
                reason="入口分类页未生成首层子任务",
                evidence=self.user_request,
                metadata={"url": current_url, "depth": "0"},
            )
            return []

        self._knowledge_entries[entry_index]["children_count"] = len(subtasks)
        self._append_journal(
            node_id=node_id,
            phase="planning",
            action="expand_category",
            reason=f"生成 {len(subtasks)} 个一级 expand 任务",
            evidence="; ".join(subtask.name for subtask in subtasks),
            metadata={"children_count": str(len(subtasks))},
        )
        for subtask in subtasks:
            self._record_planned_subtask_node(
                subtask=subtask,
                parent_node_id=node_id,
                reason="入口页面拆分出的一级任务",
            )
        return subtasks

    def _record_planning_dead_end(
        self,
        *,
        entry_index: int,
        node_id: str,
        reason: str,
        evidence: str,
        metadata: dict[str, str] | None = None,
    ) -> None:
        self._knowledge_entries[entry_index]["children_count"] = 0
        self._knowledge_entries[entry_index]["is_leaf"] = False
        self._knowledge_entries[entry_index]["executable"] = False
        self._append_journal(
            node_id=node_id,
            phase="planning",
            action="planning_dead_end",
            reason=reason,
            evidence=evidence,
            metadata=dict(metadata or {}),
        )

    def _resolve_plan_node_type_for_state(
        self,
        page_type: str,
        nav_steps: list[dict] | None,
    ) -> PlanNodeType:
        normalized = str(page_type or "").strip().lower()
        if normalized == "list_page":
            return PlanNodeType.STATEFUL_LIST if list(nav_steps or []) else PlanNodeType.LEAF
        if normalized == "category":
            return PlanNodeType.CATEGORY
        return PlanNodeType.CATEGORY

    def _build_variant_label(self, context: dict[str, str] | None) -> str | None:
        label = self._format_context_path(context)
        if not label or label == "无":
            return None
        return label

    def _build_subtasks_from_variants(
        self,
        variants: list[ResolvedPlannerVariant],
        *,
        analysis: dict,
        depth: int,
        mode: SubTaskMode = SubTaskMode.COLLECT,
        parent_id: str | None = None,
        parent_execution_brief: ExecutionBrief | None = None,
    ) -> list[SubTask]:
        subtasks: list[SubTask] = []
        seen_signatures: set[str] = set()
        raw_subtasks = list(analysis.get("subtasks") or [])

        for idx, variant in enumerate(variants):
            page_state_signature = str(variant.page_state_signature or "").strip()
            if not page_state_signature or page_state_signature in seen_signatures:
                continue
            seen_signatures.add(page_state_signature)

            raw = raw_subtasks[idx] if idx < len(raw_subtasks) else {}
            name = str(raw.get("name") or variant.variant_label or f"分类_{idx + 1}").strip()
            sanitized_context = self._sanitize_context(variant.context)
            task_desc = (
                str(raw.get("task_description") or "").strip()
                or self._build_task_description_for_mode(sanitized_context, mode)
            )
            execution_brief = self._build_execution_brief(
                context=sanitized_context,
                mode=mode,
                task_description=task_desc,
                parent_execution_brief=parent_execution_brief,
            )
            subtasks.append(
                SubTask(
                    id=self._build_subtask_id(
                        mode=mode,
                        page_state_signature=page_state_signature,
                        context=sanitized_context,
                        fallback_index=idx + 1,
                    ),
                    name=name,
                    list_url=variant.resolved_url,
                    anchor_url=variant.anchor_url,
                    page_state_signature=page_state_signature,
                    variant_label=variant.variant_label or self._build_variant_label(variant.context),
                    task_description=task_desc,
                    priority=idx,
                    max_pages=raw.get("estimated_pages"),
                    nav_steps=list(variant.nav_steps or []),
                    context=sanitized_context,
                    parent_id=parent_id,
                    depth=depth + 1,
                    mode=mode,
                    execution_brief=execution_brief,
                )
            )
        return subtasks

    def _build_subtask_id(
        self,
        *,
        mode: SubTaskMode,
        page_state_signature: str,
        context: dict[str, str] | None,
        fallback_index: int,
    ) -> str:
        base = (
            str(page_state_signature or "").strip()
            or self._format_context_path(context)
            or f"task_{fallback_index}"
        )
        digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]
        prefix = "expand" if mode == SubTaskMode.EXPAND else "leaf"
        return f"{prefix}_{digest}"

    def _record_planned_subtask_node(
        self,
        *,
        subtask: SubTask,
        parent_node_id: str | None,
        reason: str,
    ) -> None:
        node_id = self._next_node_id()
        self._knowledge_entries.append({
            "node_id": node_id,
            "parent_node_id": parent_node_id,
            "depth": int(subtask.depth or 0),
            "url": subtask.list_url,
            "anchor_url": subtask.anchor_url or subtask.list_url,
            "page_state_signature": subtask.page_state_signature,
            "variant_label": subtask.variant_label,
            "page_type": "list_page" if subtask.mode == SubTaskMode.COLLECT else "category",
            "name": subtask.name,
            "observations": "",
            "children_count": 0,
            "is_leaf": subtask.mode == SubTaskMode.COLLECT,
            "task_description": subtask.task_description,
            "context": dict(subtask.context or {}),
            "nav_steps": list(subtask.nav_steps or []),
            "subtask_id": subtask.id,
            "executable": True,
            "node_type": (
                PlanNodeType.STATEFUL_LIST.value
                if subtask.mode == SubTaskMode.COLLECT and list(subtask.nav_steps or [])
                else (PlanNodeType.LEAF.value if subtask.mode == SubTaskMode.COLLECT else PlanNodeType.CATEGORY.value)
            ),
        })
        self._append_journal(
            node_id=node_id,
            phase="planning",
            action="create_subtask",
            reason=reason,
            evidence=subtask.task_description,
            metadata={
                "subtask_id": subtask.id,
                "mode": subtask.mode.value,
                "page_state_signature": str(subtask.page_state_signature or ""),
            },
        )

    def _build_task_description_for_mode(
        self,
        context: dict[str, str] | None,
        mode: SubTaskMode,
    ) -> str:
        if mode == SubTaskMode.EXPAND:
            return self._build_expand_task_description(context)
        return self._build_collect_task_description(context)

    def _build_expand_task_description(self, context: dict[str, str] | None) -> str:
        scope = self._format_context_path(context)
        count_text = self._resolve_requested_count_text()
        suffix = f"{count_text}" if count_text else ""
        return f"爬取“{scope}”下各个相关分类的项目{suffix}。"

    def _build_collect_task_description(self, context: dict[str, str] | None) -> str:
        scope = self._format_context_path(context)
        count_text = self._resolve_requested_count_text(prefix='前')
        quantity = f"{count_text}" if count_text else "相关"
        return f"采集当前“{scope}”范围下{quantity}项目记录，提取项目名称与所属分类名称。"

    def _resolve_requested_count_text(self, prefix: str = "各") -> str:
        match = re.search(r"(\d+)\s*条", str(self.user_request or ""))
        if match:
            return f"{prefix}{match.group(1)}条"
        return ""

    def _build_execution_brief(
        self,
        *,
        context: dict[str, str] | None,
        mode: SubTaskMode,
        task_description: str,
        parent_execution_brief: ExecutionBrief | None = None,
    ) -> ExecutionBrief:
        category_path = self._extract_category_path(context)
        current_scope = category_path[-1] if category_path else str((context or {}).get("category_name") or "").strip()
        parent_chain = [item for item in category_path[:-1] if item]
        if parent_execution_brief and not parent_chain:
            parent_chain = list(parent_execution_brief.parent_chain or [])
        if mode == SubTaskMode.EXPAND:
            next_action = (
                f"先判断当前页面是否仍存在属于“{current_scope}”的下级相关分类入口；"
                "若存在则新增子任务，不直接进入详情链接采集。"
            )
            stop_rule = (
                "当页面未识别出更深相关分类，或剩余入口仅为兄弟切换、祖先回跳、筛选项或详情链接时，"
                "停止拆分并开始采集当前分类。"
            )
            do_not = [
                "不要把祖先分类或返回上一级入口当作新的子任务",
                "不要把同层兄弟分类切换误判为继续下钻",
                "不要在仍需继续拆分时直接采集当前列表",
            ]
        else:
            next_action = "直接在当前页面收集详情链接并翻页，不再继续拆分分类。"
            stop_rule = "当无新详情链接、达到目标数量，或无法继续翻页时结束当前采集任务。"
            do_not = [
                "不要再把兄弟分类切换或祖先回跳入口当作新的分类任务",
                "不要偏离当前分类作用域去采集其他分类的数据",
            ]
        return ExecutionBrief(
            parent_chain=parent_chain,
            current_scope=current_scope,
            objective=task_description,
            next_action=next_action,
            stop_rule=stop_rule,
            do_not=do_not,
        )

    def _build_collect_execution_brief(
        self,
        context: dict[str, str] | None,
        *,
        task_description: str,
        parent_execution_brief: ExecutionBrief | None = None,
    ) -> ExecutionBrief:
        return self._build_execution_brief(
            context=context,
            mode=SubTaskMode.COLLECT,
            task_description=task_description,
            parent_execution_brief=parent_execution_brief,
        )

    def _register_sibling_categories(self, subtasks: list[SubTask]) -> None:
        registry = self._get_sibling_category_registry()
        for subtask in subtasks:
            category_path = self._extract_category_path(subtask.context)
            parent_signature = self._build_parent_category_signature(category_path)
            leaf_label = self._normalize_category_leaf_label(category_path[-1] if category_path else "")
            if not parent_signature or not leaf_label:
                continue
            registry.setdefault(parent_signature, set()).add(leaf_label)

    def _get_sibling_category_registry(self) -> dict[str, set[str]]:
        registry = getattr(self, "_sibling_category_registry", None)
        if registry is None:
            registry = {}
            self._sibling_category_registry = registry
        return registry

    def _build_page_state_signature(self, current_url: str, nav_steps: list[dict] | None) -> str:
        """构造 URL + nav_steps 的稳定状态签名。"""
        return self._page_state.build_page_state_signature(current_url, nav_steps)

    async def _restore_page_state(self, target_url: str, nav_steps: list[dict] | None) -> bool:
        """恢复到指定页面状态：先回到 anchor URL，再重放导航动作。"""
        return await self._page_state.restore_page_state(target_url, nav_steps)

    async def _enter_child_state(
        self,
        current_url: str,
        child_url: str,
        child_nav_steps: list[dict] | None,
        current_nav_steps: list[dict] | None,
    ) -> bool:
        """进入子节点状态，兼容普通跳转与同 URL 内态切换。"""
        return await self._page_state.enter_child_state(
            current_url,
            child_url,
            child_nav_steps,
            current_nav_steps,
        )


    def _build_planner_candidates(self, snapshot: object, max_candidates: int = 30) -> str:
        """构建提供给 LLM 的候选分类元素列表（文本优先，不依赖截图框号）。"""
        marks = getattr(snapshot, "marks", None) or []
        if not marks:
            return "无"

        interactive_roles = {"link", "tab", "menuitem", "button", "option", "treeitem"}
        candidates: list[tuple[int, str]] = []

        for mark in marks:
            text = str(getattr(mark, "text", "") or "").strip()
            aria_label = str(getattr(mark, "aria_label", "") or "").strip()
            href = str(getattr(mark, "href", "") or "").strip()
            tag = str(getattr(mark, "tag", "") or "").lower()
            role = str(getattr(mark, "role", "") or "").lower()

            if tag not in {"a", "button", "li", "div", "span"} and role not in interactive_roles:
                continue
            label = text or aria_label
            if not label:
                continue

            score = 0
            if tag == "a":
                score += 3
            if role in {"link", "tab", "menuitem"}:
                score += 2
            if href:
                score += 1
            if len(label) > 40:
                score -= 1

            line = f"- [{mark.mark_id}] {label}"
            if href:
                line += f" | href={href[:80]}"
            candidates.append((score, line))

        if not candidates:
            return "无"

        candidates.sort(key=lambda x: x[0], reverse=True)
        lines = [line for _, line in candidates[:max_candidates]]
        return "\n".join(lines) if lines else "无"

    async def _analyze_site_structure(
        self,
        screenshot_base64: str,
        snapshot: object,
        *,
        node_context: dict[str, str] | None = None,
        nav_steps: list[dict] | None = None,
    ) -> dict | None:
        """调用 LLM 视觉接口，分析带 SoM 标注的页面截图。

        Args:
            screenshot_base64: Base64 编码的页面截图（默认不含 SoM 标注框）。
            snapshot: SoM 扫描快照（用于构建候选元素列表）。

        Returns:
            dict | None: 解析后的 JSON 对象，包含 subtasks 列表；如果失败则返回 None。
        """
        # 渲染系统提示词和用户提示词
        system_prompt = render_template(
            PROMPT_TEMPLATE_PATH,
            section="analyze_site_system_prompt",
        )

        user_message = render_template(
            PROMPT_TEMPLATE_PATH,
            section="analyze_site_user_message",
            variables={
                "user_request": self.user_request,
                "current_url": self.page.url,
                "current_category_path": self._format_context_path(node_context),
                "recent_actions": self._format_recent_actions(nav_steps),
                "candidate_elements": self._build_planner_candidates(snapshot),
                "selected_skills_context": self.selected_skills_context or "当前未选择任何站点 skills。",
            },
        )

        # 构建多模态消息列表
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=[
                    {"type": "text", "text": user_message},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{screenshot_base64}"},
                    },
                ]
            ),
        ]

        try:
            logger.info("[Planner] 调用 LLM 进行多模态视觉分析...")
            response = await self.llm.ainvoke(messages)
            response_text = response.content

            # 从 LLM 响应中解析 JSON 字典
            result = parse_json_dict_from_llm(response_text)
            if result:
                result = self._post_process_analysis(result, snapshot, node_context=node_context)
                subtask_count = len(result.get("subtasks", []))
                logger.info("[Planner] LLM 识别到 %d 个候选分类", subtask_count)
                return result

            logger.warning("[Planner] LLM 响应内容不符合预期的 JSON 格式: %s", str(response_text)[:200])
        except Exception as e:
            logger.error("[Planner] 调用 LLM 分析网站结构时发生异常: %s", e)

        return None

    def _post_process_analysis(
        self,
        result: dict,
        snapshot: object,
        *,
        node_context: dict[str, str] | None = None,
    ) -> dict:
        current_context = self._sanitize_context(node_context)
        normalized = dict(result or {})
        normalized = self._prune_backtrack_subtasks(
            normalized,
            current_context,
        )
        normalized = self._collapse_sibling_switches_to_leaf(
            normalized,
            current_context,
        )
        if not self._is_multicategory_request():
            return normalized
        if self._extract_category_path(current_context):
            return normalized

        page_type = str(normalized.get("page_type") or "").strip().lower()
        requested_subtasks = self._build_requested_category_subtasks(snapshot)
        if not requested_subtasks:
            return normalized

        existing_subtasks = list(normalized.get("subtasks") or [])
        if page_type == "category" and existing_subtasks:
            return normalized

        normalized["page_type"] = "category"
        normalized["subtasks"] = requested_subtasks
        observations = str(normalized.get("observations") or "").strip()
        note = "检测到用户请求为多分类任务，按页面中可见分类入口强制拆分子任务。"
        normalized["observations"] = f"{observations}\n{note}".strip() if observations else note
        return normalized

    def _prune_backtrack_subtasks(
        self,
        result: dict,
        context: dict[str, str] | None,
    ) -> dict:
        normalized = dict(result or {})
        subtasks = list(normalized.get("subtasks") or [])
        current_path = self._extract_category_path(context)
        if not subtasks or not current_path:
            return normalized

        current_path_norm = [self._normalize_semantic_label(item) for item in current_path if item]
        current_path_norm = [item for item in current_path_norm if item]
        if not current_path_norm:
            return normalized

        filtered_subtasks: list[dict] = []
        removed_names: list[str] = []
        for item in subtasks:
            name = str(item.get("name") or item.get("link_text") or "").strip()
            candidate_path = self._expand_category_segments(name)
            candidate_path_norm = [
                self._normalize_semantic_label(segment)
                for segment in candidate_path
                if segment
            ]
            candidate_path_norm = [segment for segment in candidate_path_norm if segment]
            if not candidate_path_norm:
                filtered_subtasks.append(item)
                continue
            if self._is_backtrack_candidate(current_path_norm, candidate_path_norm):
                removed_names.append(name or "/".join(candidate_path))
                continue
            filtered_subtasks.append(item)

        if not removed_names:
            return normalized

        normalized["subtasks"] = filtered_subtasks
        if filtered_subtasks:
            observations = str(normalized.get("observations") or "").strip()
            note = f"已过滤祖先/当前分类回跳入口: {'; '.join(removed_names)}"
            normalized["observations"] = f"{observations}\n{note}".strip() if observations else note
            return normalized

        normalized["page_type"] = "list_page"
        observations = str(normalized.get("observations") or "").strip()
        note = f"候选分类仅包含祖先或当前分类回跳入口，停止继续拆分: {'; '.join(removed_names)}"
        normalized["observations"] = f"{observations}\n{note}".strip() if observations else note
        normalized["subtasks"] = []
        if not str(normalized.get("task_description") or "").strip():
            current_label = current_path[-1]
            normalized["task_description"] = (
                f"采集当前“{current_label}”分类下前 10 条招标/采购项目记录，"
                "提取项目名称与所属分类名称。"
            )
        return normalized

    def _collapse_sibling_switches_to_leaf(
        self,
        result: dict,
        context: dict[str, str] | None,
    ) -> dict:
        normalized = dict(result or {})
        page_type = str(normalized.get("page_type") or "").strip().lower()
        if page_type != "category":
            return normalized

        current_label = self._get_current_category_label(context)
        subtask_names = self._extract_subtask_names(normalized)
        if not current_label or not subtask_names:
            return normalized
        looks_like_grouped_switch = self._looks_like_sibling_switch_group(current_label, subtask_names)
        looks_like_registered_switch = self._matches_registered_sibling_switches(context, subtask_names)
        if not looks_like_grouped_switch and not looks_like_registered_switch:
            return normalized

        display_label = self._strip_category_group_prefix(current_label)
        normalized["page_type"] = "list_page"
        normalized["subtasks"] = []
        normalized["task_description"] = (
            f"采集当前“{display_label}”分类下前 10 条招标/采购项目记录，"
            "提取项目名称与所属分类名称。"
        )
        observations = str(normalized.get("observations") or "").strip()
        note = (
            "检测到当前页面已进入具体分类，页面中剩余候选项属于同层兄弟分类切换，"
            "不再继续向下拆分。"
        )
        normalized["observations"] = f"{observations}\n{note}".strip() if observations else note
        return normalized

    def _is_multicategory_request(self) -> bool:
        request = str(self.user_request or "").strip()
        if not request:
            return False
        keywords = (
            "每类",
            "各类",
            "各个相关分类",
            "各分类",
            "分别采集",
            "分类下",
        )
        return any(keyword in request for keyword in keywords)

    def _build_requested_category_subtasks(self, snapshot: object) -> list[dict]:
        marks = getattr(snapshot, "marks", None) or []
        request = str(self.user_request or "").strip()
        if not marks or not request:
            return []

        subtasks: list[dict] = []
        seen_labels: set[str] = set()
        interactive_roles = {"link", "tab", "menuitem", "button", "option", "treeitem"}
        for mark in marks:
            tag = str(getattr(mark, "tag", "") or "").strip().lower()
            role = str(getattr(mark, "role", "") or "").strip().lower()
            if tag not in {"a", "button", "li", "div", "span"} and role not in interactive_roles:
                continue

            label = str(getattr(mark, "text", "") or getattr(mark, "aria_label", "") or "").strip()
            if not self._is_requested_category_label(label, request):
                continue
            if label in seen_labels:
                continue
            seen_labels.add(label)
            subtasks.append(
                {
                    "name": label,
                    "mark_id": int(getattr(mark, "mark_id")),
                    "link_text": label,
                    "estimated_pages": None,
                    "task_description": self._build_requested_category_task_description(label),
                }
            )
        return subtasks

    def _is_requested_category_label(self, label: str, request: str) -> bool:
        text = str(label or "").strip()
        if not text:
            return False
        if len(text) > 12:
            return False
        if any(ch.isdigit() for ch in text):
            return False
        if text not in request:
            return False
        noise_tokens = ("项目", "名称", "网站", "分类", "招标", "采购")
        return text not in noise_tokens

    def _build_requested_category_task_description(self, category_name: str) -> str:
        return (
            f"进入“{category_name}”分类，采集该分类下前 10 条招标/采购项目记录，"
            "提取项目名称与所属分类名称。"
        )

    def _extract_subtask_names(self, result: dict) -> list[str]:
        names: list[str] = []
        for item in list(result.get("subtasks") or []):
            name = str(item.get("name") or item.get("link_text") or "").strip()
            if name:
                names.append(name)
        return names

    def _get_current_category_label(self, context: dict[str, str] | None) -> str:
        raw_path = str((context or {}).get(CATEGORY_PATH_KEY) or "").strip()
        if raw_path:
            raw_parts = [item.strip() for item in raw_path.split(CATEGORY_PATH_SEPARATOR) if item.strip()]
            if raw_parts:
                return raw_parts[-1]
        return str((context or {}).get("category_name") or "").strip()

    def _expand_category_segments(self, label: str) -> list[str]:
        text = str(label or "").strip()
        if not text:
            return []
        group, leaf = self._split_grouped_category_label(text)
        if group and leaf:
            return [group, leaf]
        return [text]

    def _split_grouped_category_label(self, label: str) -> tuple[str, str]:
        text = str(label or "").strip()
        if not text:
            return "", ""
        for separator in ("-", "—", "–", ":", "：", "/", "|"):
            if separator not in text:
                continue
            group, leaf = text.split(separator, 1)
            group = group.strip()
            leaf = leaf.strip()
            if group and leaf:
                return group, leaf
        return "", text

    def _strip_category_group_prefix(self, label: str) -> str:
        _, leaf = self._split_grouped_category_label(label)
        return leaf or str(label or "").strip()

    def _normalize_category_leaf_label(self, label: str) -> str:
        return self._normalize_semantic_label(self._strip_category_group_prefix(label))

    def _build_parent_category_signature(self, category_path: list[str]) -> str:
        parent_path: list[str] = []
        for item in list(category_path or [])[:-1]:
            normalized = self._normalize_semantic_label(item)
            if normalized:
                parent_path.append(normalized)
        return CATEGORY_PATH_SEPARATOR.join(parent_path)

    def _is_backtrack_candidate(
        self,
        current_path: list[str],
        candidate_path: list[str],
    ) -> bool:
        if not current_path or not candidate_path:
            return False
        if len(candidate_path) == 1:
            return candidate_path[0] in current_path
        if len(candidate_path) > len(current_path):
            return False
        return current_path[: len(candidate_path)] == candidate_path

    def _looks_like_sibling_switch_group(
        self,
        current_label: str,
        candidate_names: list[str],
    ) -> bool:
        current_group, current_leaf = self._split_grouped_category_label(current_label)
        if not current_group or not current_leaf:
            return False

        normalized_current_group = self._normalize_semantic_label(current_group)
        normalized_current_leaf = self._normalize_semantic_label(current_leaf)
        if not normalized_current_group or not normalized_current_leaf:
            return False

        has_peer_candidate = False
        for name in candidate_names:
            group, leaf = self._split_grouped_category_label(name)
            normalized_group = self._normalize_semantic_label(group)
            normalized_leaf = self._normalize_semantic_label(leaf)
            if not normalized_group or not normalized_leaf:
                return False
            if normalized_group != normalized_current_group:
                return False
            if normalized_leaf != normalized_current_leaf:
                has_peer_candidate = True
        return has_peer_candidate

    def _matches_registered_sibling_switches(
        self,
        context: dict[str, str] | None,
        candidate_names: list[str],
    ) -> bool:
        current_path = self._extract_category_path(context)
        if len(current_path) < 2:
            return False

        parent_signature = self._build_parent_category_signature(current_path)
        registered = self._get_sibling_category_registry().get(parent_signature) or set()
        if len(registered) < 2:
            return False

        candidate_labels: set[str] = set()
        for name in candidate_names:
            normalized = self._normalize_category_leaf_label(name)
            if normalized:
                candidate_labels.add(normalized)
        if not candidate_labels:
            return False

        current_label = self._normalize_category_leaf_label(current_path[-1])
        return candidate_labels.issubset(registered) and any(
            label != current_label for label in candidate_labels
        )

    async def _resolve_mark_id_from_link_text(self, snapshot: object, link_text: str) -> int | None:
        """根据分类文本解析 mark_id（仅在歧义时触发文本消歧）。"""
        target = str(link_text or "").strip()
        if not target:
            return None

        marks = getattr(snapshot, "marks", None) or []
        if not marks:
            return None

        normalized_target = "".join(target.lower().split())
        exact_candidates: list[int] = []
        fuzzy_candidates: list[int] = []

        for mark in marks:
            text = str(getattr(mark, "text", "") or "").strip()
            aria_label = str(getattr(mark, "aria_label", "") or "").strip()
            haystack = " ".join([text, aria_label]).strip()
            if not haystack:
                continue
            normalized_haystack = "".join(haystack.lower().split())
            if not normalized_haystack:
                continue
            if normalized_haystack == normalized_target:
                exact_candidates.append(mark.mark_id)
            elif normalized_target in normalized_haystack or normalized_haystack in normalized_target:
                fuzzy_candidates.append(mark.mark_id)

        if len(exact_candidates) == 1:
            return exact_candidates[0]
        if not exact_candidates and len(fuzzy_candidates) == 1:
            return fuzzy_candidates[0]

        try:
            # 文本优先统一解析：多命中时会自动进入候选框消歧。
            return await resolve_single_mark_id(
                page=self.page,
                llm=self.llm,
                snapshot=snapshot,
                mark_id=None,
                target_text=target,
                max_retries=config.url_collector.max_validation_retries,
            )
        except Exception:
            if exact_candidates:
                return exact_candidates[0]
            if fuzzy_candidates:
                return fuzzy_candidates[0]
            return None

    async def _extract_subtask_variants(
        self,
        analysis: dict,
        snapshot: object,
        parent_nav_steps: list[dict] | None = None,
        parent_context: dict[str, str] | None = None,
    ) -> list[ResolvedPlannerVariant]:
        """根据 LLM 分析结果，为每个候选分类解析目标页面状态。"""
        raw_subtasks = analysis.get("subtasks", [])
        if not raw_subtasks:
            return []

        variants: list[ResolvedPlannerVariant] = []
        seen_signatures: set[str] = set()
        base_url = self.page.url
        original_url = self.page.url

        for idx, raw in enumerate(raw_subtasks):
            name = raw.get("name", f"分类_{idx + 1}")
            link_text = str(raw.get("link_text") or name or "").strip()
            try:
                mark_id = int(raw.get("mark_id")) if raw.get("mark_id") is not None else None
            except (TypeError, ValueError):
                mark_id = None
            if mark_id is None and link_text:
                mark_id = await self._resolve_mark_id_from_link_text(snapshot, link_text)
                if mark_id is not None:
                    logger.info("[Planner] [%s] 文本解析到 mark_id=%s", name, mark_id)

            resolved_url = ""
            variant_nav_steps = list(parent_nav_steps or [])
            same_page_variant = False
            child_context = self._build_subtask_context(name, parent_context=parent_context)

            if mark_id is not None and hasattr(snapshot, "marks"):
                for mark in snapshot.marks:
                    if mark.mark_id == mark_id and mark.href:
                        _href_lower = str(mark.href).strip().lower()
                        if _href_lower.startswith("javascript:") or _href_lower in ("#", ""):
                            logger.info(
                                "[Planner] [%s] 策略1：mark href 无效（已过滤）: %s", name, mark.href[:80]
                            )
                            break
                        resolved_url = urljoin(base_url, mark.href)
                        if resolved_url.lower() == base_url.lower() or resolved_url.lower() == original_url.lower():
                            logger.info(
                                "[Planner] [%s] 策略1：mark href 指向当前页（已过滤）: %s", name, resolved_url[:80]
                            )
                            resolved_url = ""
                            break
                        logger.info("[Planner] [%s] 策略1：从 mark href 获取 URL: %s", name, resolved_url[:80])
                        break

            if not resolved_url and mark_id is not None:
                resolved_url = await self._get_href_by_js(mark_id, base_url, snapshot)
                if resolved_url:
                    _lower = resolved_url.strip().lower()
                    if (
                        _lower.startswith("javascript:")
                        or _lower in ("#", "")
                        or _lower == base_url.lower()
                        or _lower == original_url.lower()
                    ):
                        logger.info(
                            "[Planner] [%s] 策略2：JS 返回无效 URL（已过滤）: %s", name, resolved_url[:80]
                        )
                        resolved_url = ""
                    else:
                        logger.info("[Planner] [%s] 策略2：从 JS 属性获取 URL: %s", name, resolved_url[:80])

            if not resolved_url and mark_id is not None:
                resolved = await self._get_url_by_navigation(
                    mark_id,
                    original_url,
                    snapshot,
                    parent_nav_steps=parent_nav_steps,
                    variant_label=self._build_variant_label(child_context) or str(name or "").strip(),
                    child_context=child_context,
                )
                if resolved is not None:
                    resolved_url = resolved.resolved_url
                    variant_nav_steps = list(resolved.nav_steps or variant_nav_steps)
                    same_page_variant = resolved.same_page_variant
                    logger.info(
                        "[Planner] [%s] 策略3：解析到页面状态: %s",
                        name,
                        str(resolved.page_state_signature or resolved.resolved_url)[:80],
                    )
                elif self._looks_like_current_category(name, analysis):
                    resolved_url = original_url
                    variant_nav_steps = list(parent_nav_steps or [])
                    logger.info(
                        "[Planner] [%s] 策略3：识别为当前已选分类，直接复用当前页面状态",
                        name,
                    )

            if not resolved_url:
                logger.warning(
                    "[Planner] [%s] 无法解析分类入口状态，跳过该子任务",
                    name,
                )
                continue

            page_state_signature = self._build_page_state_signature(resolved_url, variant_nav_steps)
            if page_state_signature in seen_signatures:
                logger.warning(
                    "[Planner] [%s] 解析结果与已有状态重复，跳过重复子任务: %s",
                    name,
                    page_state_signature[:80],
                )
                continue
            seen_signatures.add(page_state_signature)
            variants.append(
                ResolvedPlannerVariant(
                    resolved_url=resolved_url,
                    anchor_url=original_url,
                    nav_steps=variant_nav_steps,
                    page_state_signature=page_state_signature,
                    variant_label=self._build_variant_label(child_context) or str(name or "").strip(),
                    context=child_context,
                    same_page_variant=same_page_variant,
                )
            )

        return variants

    async def plan_runtime_subtasks(
        self,
        *,
        parent_subtask: SubTask,
        max_children: int | None = None,
    ) -> RuntimeSubtaskPlanResult:
        current_url = str(parent_subtask.anchor_url or parent_subtask.list_url or self.site_url).strip()
        current_nav_steps = list(parent_subtask.nav_steps or [])
        current_context = self._sanitize_context(parent_subtask.context)
        restored = await self._restore_page_state(current_url, current_nav_steps)
        if not restored:
            raise RuntimeError("runtime_subtask_restore_failed")

        snapshot = await inject_and_scan(self.page)
        _, screenshot_base64 = await capture_screenshot_with_marks(self.page)
        await clear_overlay(self.page)

        analysis = await self._analyze_site_structure(
            screenshot_base64,
            snapshot,
            node_context=current_context,
            nav_steps=current_nav_steps,
        )
        if not analysis:
            raise RuntimeError("runtime_subtask_analysis_failed")

        page_type = str(analysis.get("page_type", "category")).strip().lower()
        collect_desc = str(analysis.get("task_description") or "").strip() or self._build_collect_task_description(current_context)
        collect_brief = self._build_collect_execution_brief(
            current_context,
            task_description=collect_desc,
            parent_execution_brief=parent_subtask.execution_brief,
        )
        if page_type == "list_page":
            return RuntimeSubtaskPlanResult(
                page_type=page_type,
                analysis=analysis,
                collect_task_description=collect_desc,
                collect_execution_brief=collect_brief,
            )

        child_variants = await self._extract_subtask_variants(
            analysis,
            snapshot,
            parent_nav_steps=current_nav_steps,
            parent_context=current_context,
        )
        children = self._build_subtasks_from_variants(
            child_variants,
            analysis=analysis,
            depth=int(parent_subtask.depth or 0),
            mode=SubTaskMode.EXPAND,
            parent_id=parent_subtask.id,
            parent_execution_brief=parent_subtask.execution_brief,
        )
        if max_children is not None and max_children > 0:
            children = children[:max_children]
        if not children:
            return RuntimeSubtaskPlanResult(
                page_type="list_page",
                analysis=analysis,
                collect_task_description=collect_desc,
                collect_execution_brief=collect_brief,
            )

        return RuntimeSubtaskPlanResult(
            page_type=page_type,
            analysis=analysis,
            children=children,
            collect_task_description=collect_desc,
            collect_execution_brief=collect_brief,
        )

    def _looks_like_current_category(self, name: str, analysis: dict) -> bool:
        label = str(name or "").strip()
        if not label:
            return False
        observations = str(analysis.get("observations") or "").strip()
        if not observations:
            return False
        selected_markers = ("当前选中", "当前高亮", "默认", "已选中")
        return label in observations and any(marker in observations for marker in selected_markers)

    def _get_best_xpath_for_mark(self, snapshot: object, mark_id: int) -> str | None:
        """从 snapshot 中获取指定 mark_id 的最佳原生 XPath。"""
        marks = getattr(snapshot, "marks", None) or []
        for mark in marks:
            if mark.mark_id == mark_id:
                candidates = getattr(mark, "xpath_candidates", None) or []
                if candidates:
                    return candidates[0].xpath
        return None

    async def _get_href_by_js(self, mark_id: int, base_url: str, snapshot: object) -> str:
        """通过 XPath 定位 DOM 元素并读取其 href 属性。"""
        xpath = self._get_best_xpath_for_mark(snapshot, mark_id)
        if not xpath:
            return ""
        try:
            href = await self.page.evaluate(
                """(xpath) => {
                    const result = document.evaluate(
                        xpath, document, null,
                        XPathResult.FIRST_ORDERED_NODE_TYPE, null
                    );
                    const el = result.singleNodeValue;
                    if (!el) return null;
                    if (el.href) return el.href;
                    const anchor = el.closest('a');
                    if (anchor && anchor.href) return anchor.href;
                    return null;
                }""",
                xpath,
            )
            if href:
                return urljoin(base_url, href)
        except Exception as e:
            logger.debug("[Planner] JS 执行获取 mark_id=%d 的 href 失败: %s", mark_id, e)
        return ""

    async def _get_url_by_navigation(
        self,
        mark_id: int,
        original_url: str,
        snapshot: object,
        parent_nav_steps: list[dict] | None = None,
        variant_label: str = "",
        child_context: dict[str, str] | None = None,
    ) -> ResolvedPlannerVariant | None:
        """针对 SPA 网站的兜底策略：通过原生 XPath 定位元素，模拟点击并检测页面状态变化。"""
        xpath = self._get_best_xpath_for_mark(snapshot, mark_id)
        if not xpath:
            logger.debug("[Planner]   mark_id=%d 在 snapshot 中无可用 XPath", mark_id)
            return None

        nav_step_record = self._build_nav_click_step(snapshot, mark_id)
        if not nav_step_record:
            logger.debug("[Planner]   mark_id=%d 无法构造导航回放动作", mark_id)
            return None

        try:
            logger.info("[Planner]   触发模拟点击 mark_id=%d (xpath=%s)...", mark_id, xpath[:60])

            url_before = self.page.url
            dom_sig_before = await self._get_dom_signature()

            locator = self.page.locator(f"xpath={xpath}")
            if await locator.count() == 0:
                logger.warning("[Planner]   XPath 未匹配到元素: %s", xpath[:80])
                return None

            await locator.first.click(timeout=5000)
            await self.page.wait_for_timeout(2000)

            url_after = self.page.url
            old_parsed = urlparse(url_before)
            new_parsed = urlparse(url_after)
            url_changed = url_after != url_before or old_parsed.fragment != new_parsed.fragment

            logger.info(
                "[Planner]   URL 比较: before=%s | after=%s | fragment: %s -> %s | changed=%s",
                url_before[:80],
                url_after[:80],
                old_parsed.fragment[:40] if old_parsed.fragment else '(none)',
                new_parsed.fragment[:40] if new_parsed.fragment else '(none)',
                url_changed,
            )

            if url_changed and url_after:
                await self._restore_page_state(original_url, parent_nav_steps)
                nav_steps = list(parent_nav_steps or [])
                return ResolvedPlannerVariant(
                    resolved_url=url_after,
                    anchor_url=url_after,
                    nav_steps=nav_steps,
                    page_state_signature=self._build_page_state_signature(url_after, nav_steps),
                    variant_label=variant_label,
                    context=self._sanitize_context(child_context),
                    same_page_variant=False,
                )

            dom_sig_after = await self._get_dom_signature()
            logger.info(
                "[Planner]   DOM 签名比较: before=%s | after=%s | changed=%s",
                dom_sig_before[:16] if dom_sig_before else '(empty)',
                dom_sig_after[:16] if dom_sig_after else '(empty)',
                dom_sig_before != dom_sig_after if (dom_sig_before and dom_sig_after) else 'N/A',
            )
            if dom_sig_after and dom_sig_after != dom_sig_before:
                child_nav_steps = list(parent_nav_steps or []) + [nav_step_record]
                await self._restore_page_state(original_url, parent_nav_steps)
                return ResolvedPlannerVariant(
                    resolved_url=url_before,
                    anchor_url=original_url,
                    nav_steps=child_nav_steps,
                    page_state_signature=self._build_page_state_signature(url_before, child_nav_steps),
                    variant_label=variant_label,
                    context=self._sanitize_context(child_context),
                    same_page_variant=True,
                )

            logger.info("[Planner]   模拟点击后 URL 和 DOM 均未发生显著变化")
        except Exception as e:
            logger.debug("[Planner]   模拟点击导航 mark_id=%d 失败: %s", mark_id, e)
            await self._restore_page_state(original_url, parent_nav_steps)

        return None

    def _build_nav_click_step(self, snapshot: object, mark_id: int) -> dict | None:
        """基于 snapshot 为 planner 构造可回放的点击动作。"""
        return self._page_state.build_nav_click_step(snapshot, mark_id)

    async def _get_dom_signature(self) -> str:
        """获取页面 DOM 内容签名，用于检测内容变化。"""
        return await self._page_state.get_dom_signature()

    async def _restore_original_page(self, original_url: str) -> None:
        """回退到原始页面，等待 SPA 渲染完成。"""
        await self._page_state.restore_original_page(original_url)

    def _build_plan(self, subtasks: list[SubTask]) -> TaskPlan:
        """构造 TaskPlan 响应对象。"""
        return self._artifacts.build_plan(
            subtasks,
            nodes=self._build_plan_nodes(),
            journal=self._build_plan_journal(),
        )

    def _build_plan_id(self) -> str:
        return self._artifacts._build_plan_id()

    def _load_saved_plan(self) -> TaskPlan | None:
        return self._artifacts._load_saved_plan()

    def _create_empty_plan(self) -> TaskPlan:
        """当分析失败或 LLM 未产生结果时，返回一个没有任何子任务的空计划。"""
        return self._artifacts.create_empty_plan()

    def _save_plan(self, plan: TaskPlan) -> TaskPlan:
        """将生成的任务计划序列化为 JSON 文件，存储在指定的输出目录中。"""
        return self._artifacts.save_plan(plan)

    def _write_knowledge_doc(self, plan: TaskPlan) -> None:
        """将规划发现过程写成层次化的 Markdown 知识文档。"""
        self._artifacts.write_knowledge_doc(plan)

    def render_plan_knowledge(self, plan: TaskPlan) -> str:
        return self._artifacts.build_knowledge_doc(plan)

    def _sediment_draft_skill(self, plan: TaskPlan) -> None:
        """规划完成后立即生成 draft Skill，不等 Worker 执行。"""
        self._artifacts.sediment_draft_skill(plan)

    def _build_plan_nodes(self) -> list[PlanNode]:
        nodes: list[PlanNode] = []
        for raw in self._knowledge_entries:
            node_type = self._resolve_plan_node_type(raw)
            nodes.append(
                PlanNode(
                    node_id=str(raw.get("node_id") or ""),
                    parent_node_id=str(raw.get("parent_node_id") or "") or None,
                    name=str(raw.get("name") or ""),
                    node_type=node_type,
                    url=str(raw.get("url") or ""),
                    anchor_url=str(raw.get("anchor_url") or "") or None,
                    page_state_signature=str(raw.get("page_state_signature") or "") or None,
                    variant_label=str(raw.get("variant_label") or "") or None,
                    task_description=str(raw.get("task_description") or ""),
                    observations=str(raw.get("observations") or ""),
                    depth=int(raw.get("depth", 0) or 0),
                    nav_steps=list(raw.get("nav_steps") or []),
                    context=dict(raw.get("context") or {}),
                    subtask_id=str(raw.get("subtask_id") or "") or None,
                    is_leaf=bool(raw.get("is_leaf", False)),
                    executable=bool(raw.get("executable", False)),
                    children_count=int(raw.get("children_count", 0) or 0),
                )
            )
        return nodes

    def _resolve_plan_node_type(self, raw: dict[str, Any]) -> PlanNodeType:
        raw_type = str(raw.get("node_type") or raw.get("page_type") or "").strip()
        if raw.get("is_leaf") and raw_type not in {PlanNodeType.STATEFUL_LIST.value, PlanNodeType.LEAF.value}:
            return PlanNodeType.LEAF
        try:
            return PlanNodeType(raw_type)
        except ValueError:
            if raw.get("is_leaf"):
                return PlanNodeType.LEAF
            return PlanNodeType.CATEGORY

    def _build_plan_journal(self) -> list[PlanJournalEntry]:
        entries: list[PlanJournalEntry] = []
        for raw in self._journal_entries:
            entries.append(
                PlanJournalEntry(
                    entry_id=str(raw.get("entry_id") or ""),
                    node_id=str(raw.get("node_id") or "") or None,
                    phase=str(raw.get("phase") or ""),
                    action=str(raw.get("action") or ""),
                    reason=str(raw.get("reason") or ""),
                    evidence=str(raw.get("evidence") or ""),
                    metadata={str(k): str(v) for k, v in dict(raw.get("metadata") or {}).items()},
                    created_at=str(raw.get("created_at") or ""),
                )
            )
        return entries

    def _append_journal(
        self,
        *,
        node_id: str | None,
        phase: str,
        action: str,
        reason: str,
        evidence: str = "",
        metadata: dict[str, str] | None = None,
    ) -> None:
        self._journal_entries.append({
            "entry_id": self._next_journal_id(),
            "node_id": node_id,
            "phase": phase,
            "action": action,
            "reason": reason,
            "evidence": evidence,
            "metadata": dict(metadata or {}),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })

    def _next_node_id(self) -> str:
        return f"node_{len(self._knowledge_entries) + 1:03d}"

    def _next_journal_id(self) -> str:
        return f"journal_{len(self._journal_entries) + 1:04d}"

    def _build_subtask_context(
        self,
        name: str,
        parent_context: dict[str, str] | None = None,
    ) -> dict[str, str]:
        context = self._sanitize_context(parent_context)
        value = str(name or "").strip()
        if not value:
            return context
        category_path = self._extract_category_path(context)
        if not category_path or category_path[-1] != value:
            category_path.append(value)
        context["category_name"] = value
        context[CATEGORY_PATH_KEY] = CATEGORY_PATH_SEPARATOR.join(category_path)
        return context

    def _sanitize_context(self, context: dict[str, str] | None) -> dict[str, str]:
        sanitized: dict[str, str] = {}
        for key, value in dict(context or {}).items():
            normalized_key = str(key or "").strip()
            normalized_value = str(value or "").strip()
            if normalized_key and normalized_value:
                sanitized[normalized_key] = normalized_value
        return sanitized

    def _extract_category_path(self, context: dict[str, str] | None) -> list[str]:
        raw = str((context or {}).get(CATEGORY_PATH_KEY) or "").strip()
        if not raw:
            category_name = str((context or {}).get("category_name") or "").strip()
            return self._expand_category_segments(category_name)

        expanded_path: list[str] = []
        for item in raw.split(CATEGORY_PATH_SEPARATOR):
            expanded_path.extend(self._expand_category_segments(item))
        return [item.strip() for item in expanded_path if item.strip()]

    def _normalize_semantic_label(self, value: str) -> str:
        normalized = "".join(str(value or "").split())
        if not normalized:
            return ""
        changed = True
        while changed:
            changed = False
            for suffix in SEMANTIC_CATEGORY_SUFFIXES:
                if normalized.endswith(suffix) and len(normalized) > len(suffix):
                    normalized = normalized[: -len(suffix)]
                    changed = True
                    break
        return normalized

    def _format_context_path(self, context: dict[str, str] | None) -> str:
        category_path = self._extract_category_path(context)
        return CATEGORY_PATH_SEPARATOR.join(category_path) if category_path else "无"

    def _format_recent_actions(self, nav_steps: list[dict] | None) -> str:
        lines: list[str] = []
        for step in list(nav_steps or [])[-PLANNER_ACTION_HISTORY_LIMIT:]:
            action = str(step.get("action") or "").strip().lower()
            target = str(step.get("target_text") or step.get("clicked_element_text") or "").strip()
            if not action:
                continue
            if action == "click":
                lines.append(f"- 点击：{target or '未命名元素'}")
                continue
            if action == "type":
                text = str(step.get("text") or "").strip()
                lines.append(f"- 输入：{target or '输入框'} <- {text or '(空)'}")
                continue
            if action == "scroll":
                delta = step.get("scroll_delta")
                lines.append(f"- 滚动：{delta}")
                continue
            lines.append(f"- {action}：{target or '未命名动作'}")
        return "\n".join(lines) if lines else "无"

    def _build_semantic_state_signature(
        self,
        current_url: str,
        context: dict[str, str] | None,
    ) -> str:
        normalized_url = str(current_url or "").strip()
        semantic_path = [
            self._normalize_semantic_label(item)
            for item in self._extract_category_path(context)
        ]
        semantic_path = [item for item in semantic_path if item]
        if not semantic_path:
            return normalized_url
        return f"{normalized_url}::{CATEGORY_PATH_SEPARATOR.join(semantic_path)}"

    def _is_same_page_category_cycle(
        self,
        current_url: str,
        child_url: str,
        current_context: dict[str, str] | None,
        child_context: dict[str, str] | None,
    ) -> bool:
        if str(current_url or "").strip() != str(child_url or "").strip():
            return False
        current_path = [
            self._normalize_semantic_label(item)
            for item in self._extract_category_path(current_context)
        ]
        child_path = [
            self._normalize_semantic_label(item)
            for item in self._extract_category_path(child_context)
        ]
        current_path = [item for item in current_path if item]
        child_path = [item for item in child_path if item]
        if not current_path or len(child_path) <= len(current_path):
            return False
        child_label = child_path[-1]
        return bool(child_label and child_label in current_path)
