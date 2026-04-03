"""任务规划器 (Task Planner) — 负责分析网站结构并将复杂的采集任务拆分为多个子任务。

该模块的核心逻辑是通过 LLM (语言模型) 结合视觉分析 (结合 SoM 标注的截图)，识别目标网站的导航结构
（如菜单、分类列表、频道入口等），并自动生成一系列独立的子任务。
每个子任务通常对应一个特定的分类或频道的列表页。
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ...common.config import config
from ...common.logger import get_logger
from ...common.protocol import parse_json_dict_from_llm
from ...common.som import inject_and_scan, capture_screenshot_with_marks, clear_overlay
from ...common.som.text_first import resolve_single_mark_id
from ...domain.planning import SubTask, SubTaskStatus, TaskPlan
from ...common.utils.paths import get_prompt_path
from ...common.utils.prompt_template import render_template
from .planner_artifacts import PlannerArtifacts
from .planner_state import PlannerPageState

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = get_logger(__name__)

PROMPT_TEMPLATE_PATH = get_prompt_path("planner.yaml")


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
        self._knowledge_entries: list[dict] = []  # DFS 过程中收集的知识条目
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
        """通过 DFS 遍历站点分类结构，发现所有叶子级列表页，一次性写入 Plan。

        DFS 在单个浏览器会话中完成，像人浏览网站一样顺序访问每个分类：
        - 如果是分支节点（分类页）：提取子分类，逐个 DFS 递归
        - 如果是叶子节点（列表页）：记录到 subtasks

        Returns:
            TaskPlan: 包含所有叶子子任务的计划。
        """
        logger.info("[Planner] 开始 DFS 遍历网站结构: %s", self.site_url)

        # 步骤 1: 访问目标网站
        await self.page.goto(self.site_url, wait_until="domcontentloaded", timeout=30000)
        await self.page.wait_for_timeout(2000)
        logger.info("[Planner] 页面已加载: %s", self.page.url)

        # 步骤 2: DFS 遍历
        all_subtasks: list[SubTask] = []
        visited_states: set[str] = set()

        await self._dfs_explore(
            current_url=self.page.url,
            user_request=self.user_request,
            subtasks_out=all_subtasks,
            visited_states=visited_states,
            depth=0,
        )

        # 步骤 3: 构建并保存 Plan
        plan = self._build_plan(all_subtasks)
        plan = self._save_plan(plan)

        # 步骤 4: 写出知识文档并生成初始 Skill
        self._write_knowledge_doc(plan)
        self._sediment_draft_skill(plan)

        logger.info("[Planner] DFS 遍历完成，发现 %d 个叶子任务", len(plan.subtasks))
        return plan

    async def _dfs_explore(
        self,
        current_url: str,
        user_request: str,
        subtasks_out: list[SubTask],
        visited_states: set[str],
        depth: int,
        parent_nav_steps: list[dict] | None = None,
    ) -> None:
        """DFS 递归探索一个页面节点。

        对当前页面做 SoM + LLM 分析，判断页面类型：
        - list_page（叶子）：记录到 subtasks_out
        - category（分支）：提取每个子分类 URL，逐个 DFS 递归

        Args:
            current_url: 当前页面 URL。
            user_request: 用户需求描述（可能随深度细化）。
            subtasks_out: 收集结果的列表（引用传递）。
            visited_states: 已访问状态集合（防止环路）。
            depth: 当前遍历深度。
            parent_nav_steps: 从首页到达当前页面的导航步骤（用于 Ajax 站）。
        """
        current_nav_steps = list(parent_nav_steps or [])
        state_signature = self._build_page_state_signature(current_url, current_nav_steps)
        if state_signature in visited_states:
            logger.info(
                "[Planner] DFS(depth=%d) 跳过已访问状态: %s",
                depth,
                state_signature[:120],
            )
            return
        visited_states.add(state_signature)

        logger.info("[Planner] DFS(depth=%d) 分析页面: %s", depth, current_url[:80])

        # 1. SoM 分析当前页面
        snapshot = await inject_and_scan(self.page)
        _, screenshot_base64 = await capture_screenshot_with_marks(self.page)
        await clear_overlay(self.page)

        # 2. LLM 判断页面类型
        analysis = await self._analyze_site_structure(screenshot_base64, snapshot)

        if not analysis:
            logger.warning("[Planner] DFS(depth=%d) LLM 分析失败，跳过", depth)
            return

        page_type = str(analysis.get("page_type", "category")).strip().lower()
        node_name = str(analysis.get("name", "")).strip() or f"页面_{depth}"
        observations = str(analysis.get("observations", "")).strip()

        # 记录知识条目（每个 DFS 节点都记录）
        entry_index = len(self._knowledge_entries)
        self._knowledge_entries.append({
            "depth": depth,
            "url": current_url,
            "page_type": page_type,
            "name": node_name,
            "observations": observations,
            "children_count": 0,
            "is_leaf": False,
        })

        # 3. 叶子节点：当前页就是列表页
        if page_type == "list_page":
            self._knowledge_entries[entry_index]["is_leaf"] = True
            subtask = SubTask(
                id=f"leaf_{len(subtasks_out) + 1:03d}",
                name=node_name,
                list_url=current_url,
                task_description=analysis.get("task_description", user_request),
                nav_steps=list(parent_nav_steps or []),
                depth=depth,
                priority=len(subtasks_out),
            )
            subtasks_out.append(subtask)
            logger.info(
                "[Planner] DFS(depth=%d) ✓ 发现叶子任务: %s → %s",
                depth, subtask.name, current_url[:80],
            )
            return

        # 4. 分支节点：提取子分类并逐个 DFS 递归
        raw_children = analysis.get("subtasks", [])
        if not raw_children:
            # LLM 说是分类页但没识别到子分类 → 当列表页兜底
            self._knowledge_entries[entry_index]["is_leaf"] = True
            subtask = SubTask(
                id=f"leaf_{len(subtasks_out) + 1:03d}",
                name=node_name,
                list_url=current_url,
                task_description=user_request,
                nav_steps=list(parent_nav_steps or []),
                depth=depth,
                priority=len(subtasks_out),
            )
            subtasks_out.append(subtask)
            logger.info(
                "[Planner] DFS(depth=%d) ✓ 无子分类，兜底为叶子任务: %s",
                depth, current_url[:80],
            )
            return

        # 复用现有的 URL 提取逻辑获取每个子分类的 URL
        children_with_urls = await self._extract_subtask_urls(analysis, snapshot, current_nav_steps)

        if not children_with_urls:
            # 提取全部失败 → 兜底
            self._knowledge_entries[entry_index]["is_leaf"] = True
            subtask = SubTask(
                id=f"leaf_{len(subtasks_out) + 1:03d}",
                name=node_name,
                list_url=current_url,
                task_description=user_request,
                nav_steps=list(parent_nav_steps or []),
                depth=depth,
                priority=len(subtasks_out),
            )
            subtasks_out.append(subtask)
            logger.info(
                "[Planner] DFS(depth=%d) ✓ URL 提取全部失败，兜底为叶子任务: %s",
                depth, current_url[:80],
            )
            return

        # 更新知识条目的子分类数
        self._knowledge_entries[entry_index]["children_count"] = len(children_with_urls)

        logger.info(
            "[Planner] DFS(depth=%d) 发现 %d 个子分类，开始逐个递归",
            depth, len(children_with_urls),
        )

        for child in children_with_urls:
            child_url = child.list_url
            child_desc = child.task_description
            child_nav_steps = list(child.nav_steps or current_nav_steps)

            await self._restore_page_state(current_url, current_nav_steps)

            child_state_signature = self._build_page_state_signature(child_url, child_nav_steps)
            if child_state_signature in visited_states:
                logger.info(
                    "[Planner] DFS(depth=%d) 跳过已访问子状态: %s",
                    depth + 1,
                    child_state_signature[:120],
                )
                continue

            if not await self._enter_child_state(current_url, child_url, child_nav_steps, current_nav_steps):
                logger.warning(
                    "[Planner] DFS(depth=%d) 进入子状态失败，跳过: %s",
                    depth + 1,
                    child_desc[:80],
                )
                continue

            await self._dfs_explore(
                current_url=child_url,
                user_request=child_desc,
                subtasks_out=subtasks_out,
                visited_states=visited_states,
                depth=depth + 1,
                parent_nav_steps=child_nav_steps,
            )

        await self._restore_page_state(current_url, current_nav_steps)

    def _stable_nav_step_payload(self, step: dict) -> dict:
        """提取用于状态判重的稳定导航字段。"""
        return self._page_state.stable_nav_step_payload(step)

    def _normalize_nav_steps(self, nav_steps: list[dict] | None) -> list[dict]:
        """规范化导航步骤，去掉不稳定字段。"""
        return self._page_state.normalize_nav_steps(nav_steps)

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

    async def _analyze_site_structure(self, screenshot_base64: str, snapshot: object) -> dict | None:
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
                subtask_count = len(result.get("subtasks", []))
                logger.info("[Planner] LLM 识别到 %d 个候选分类", subtask_count)
                return result

            logger.warning("[Planner] LLM 响应内容不符合预期的 JSON 格式: %s", str(response_text)[:200])
        except Exception as e:
            logger.error("[Planner] 调用 LLM 分析网站结构时发生异常: %s", e)

        return None

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

    async def _extract_subtask_urls(
        self, analysis: dict, snapshot: object, parent_nav_steps: list[dict] | None = None
    ) -> list[SubTask]:
        """根据 LLM 的分析结果，为每个识别出的分类提取真实的列表页 URL。

        此方法采用了多重兜底策略来应对不同架构的网站：
        1. 优先从 SoM 快照的静态属性中查找 href。
        2. 其次通过执行 JavaScript 获取元素的 href 或最近祖先 A 标签的 href。
        3. 针对 SPA（单页应用），采用模拟点击并监控 URL 变化的方式获取。
        4. 如果以上都失效，显式跳过该分类，避免把规划失败伪装成“当前页可执行”。

        Args:
            analysis: LLM 返回的分类分析字典。
            snapshot: SoM 扫描产生的页面快照对象。

        Returns:
            list[SubTask]: 最终生成的子任务列表。
        """
        raw_subtasks = analysis.get("subtasks", [])
        if not raw_subtasks:
            return []

        subtasks: list[SubTask] = []
        seen_signatures: set[tuple[str, str]] = set()
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
            task_desc = raw.get("task_description", f"采集 {name} 分类的数据")

            list_url = ""
            
            # 策略 1: 直接从 SoM 快照 (snapshot.marks) 的 href 属性获取
            if mark_id is not None and hasattr(snapshot, "marks"):
                for mark in snapshot.marks:
                    if mark.mark_id == mark_id and mark.href:
                        _href_lower = str(mark.href).strip().lower()
                        if _href_lower.startswith("javascript:") or _href_lower in ("#", ""):
                            logger.info(
                                "[Planner] [%s] 策略1：mark href 无效（已过滤）: %s", name, mark.href[:80]
                            )
                            break
                        list_url = urljoin(base_url, mark.href)
                        if list_url.lower() == base_url.lower() or list_url.lower() == original_url.lower():
                            logger.info(
                                "[Planner] [%s] 策略1：mark href 指向当前页（已过滤）: %s", name, list_url[:80]
                            )
                            list_url = ""
                            break
                        logger.info("[Planner] [%s] 策略1：从 mark href 获取 URL: %s", name, list_url[:80])
                        break

            # 策略 2: 注入 JavaScript 读取 DOM 元素的 href（通过原生 XPath 定位）
            if not list_url and mark_id is not None:
                list_url = await self._get_href_by_js(mark_id, base_url, snapshot)
                if list_url:
                    # 过滤无效 URL（javascript:, #, 空白等）
                    _lower = list_url.strip().lower()
                    if (
                        _lower.startswith("javascript:")
                        or _lower in ("#", "")
                        or _lower == base_url.lower()
                        or _lower == original_url.lower()
                    ):
                        logger.info(
                            "[Planner] [%s] 策略2：JS 返回无效 URL（已过滤）: %s", name, list_url[:80]
                        )
                        list_url = ""
                    else:
                        logger.info("[Planner] [%s] 策略2：从 JS 属性获取 URL: %s", name, list_url[:80])

            # 策略 3: SPA 兜底 — 模拟点击元素，观察 URL 或 DOM 变化（通过原生 XPath 定位）
            nav_steps_for_child = list(parent_nav_steps or [])
            if not list_url and mark_id is not None:
                list_url, navigation_steps = await self._get_url_by_navigation(
                    mark_id,
                    original_url,
                    snapshot,
                    parent_nav_steps=parent_nav_steps,
                )
                if list_url:
                    nav_steps_for_child = list(navigation_steps or nav_steps_for_child)
                    logger.info("[Planner] [%s] 策略3：通过 SPA 模拟点击获取 URL: %s", name, list_url[:80])

            if not list_url:
                logger.warning(
                    "[Planner] [%s] 无法解析分类入口 URL，跳过该子任务，避免把规划失败伪装成当前页回退",
                    name,
                )
                continue

            # 创建子任务实体
            signature = (list_url, task_desc.strip())
            if signature in seen_signatures:
                logger.warning(
                    "[Planner] [%s] 解析结果与已有子任务重复，跳过重复子任务: %s",
                    name,
                    list_url[:80],
                )
                continue
            seen_signatures.add(signature)

            subtask = SubTask(
                id=f"category_{idx + 1:02d}",
                name=name,
                list_url=list_url,
                task_description=task_desc,
                priority=idx,
                max_pages=raw.get("estimated_pages"),
                nav_steps=nav_steps_for_child,
            )
            subtasks.append(subtask)

        return subtasks

    def _get_best_xpath_for_mark(self, snapshot: object, mark_id: int) -> str | None:
        """从 snapshot 中获取指定 mark_id 的最佳原生 XPath。

        Args:
            snapshot: SoM 扫描快照。
            mark_id: 目标元素的 mark_id。

        Returns:
            str | None: 最高优先级的 XPath 字符串；找不到则返回 None。
        """
        marks = getattr(snapshot, "marks", None) or []
        for mark in marks:
            if mark.mark_id == mark_id:
                candidates = getattr(mark, "xpath_candidates", None) or []
                if candidates:
                    return candidates[0].xpath
        return None

    async def _get_href_by_js(self, mark_id: int, base_url: str, snapshot: object) -> str:
        """通过 XPath 定位 DOM 元素并读取其 href 属性。

        Args:
            mark_id: 元素的 SoM 标识。
            base_url: 当前页面 URL，用于拼接相对路径。
            snapshot: SoM 快照，用于获取原生 XPath。

        Returns:
            str: 绝对地址 URL，如果未找到则返回空字符串。
        """
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
    ) -> tuple[str, list[dict]]:
        """针对 SPA 网站的兜底策略：通过原生 XPath 定位元素，模拟点击并检测跳转。

        检测逻辑：
        1. 比较完整 URL 字符串是否变化。
        2. 比较 URL 的 hash fragment 是否变化（捕获 hash-based SPA 路由）。
        3. 若 URL 完全不变，检测页面 DOM 内容是否发生了更新
           （捕获纯 Ajax 加载的 SPA，点击分类后 URL 不变但列表内容已刷新）。

        Args:
            mark_id: SoM 标注的 mark_id。
            original_url: 点击前的原始 URL (用于恢复页面)。
            snapshot: SoM 快照，用于获取原生 XPath 定位元素。

        Returns:
            tuple[str, list[dict]]: 点击跳转后的新 URL 以及到达子状态的导航链；
                若 URL 和 DOM 均未发生变化，则返回 ("", 原父导航链)。
        """
        xpath = self._get_best_xpath_for_mark(snapshot, mark_id)
        if not xpath:
            logger.debug("[Planner]   mark_id=%d 在 snapshot 中无可用 XPath", mark_id)
            return "", list(parent_nav_steps or [])

        nav_step_record = self._build_nav_click_step(snapshot, mark_id)
        if not nav_step_record:
            logger.debug("[Planner]   mark_id=%d 无法构造导航回放动作", mark_id)
            return "", list(parent_nav_steps or [])

        try:
            logger.info("[Planner]   触发模拟点击 mark_id=%d (xpath=%s)...", mark_id, xpath[:60])

            url_before = self.page.url
            dom_sig_before = await self._get_dom_signature()

            locator = self.page.locator(f"xpath={xpath}")

            if await locator.count() == 0:
                logger.warning("[Planner]   XPath 未匹配到元素: %s", xpath[:80])
                return "", list(parent_nav_steps or [])

            await locator.first.click(timeout=5000)
            await self.page.wait_for_timeout(2000)

            url_after = self.page.url

            old_parsed = urlparse(url_before)
            new_parsed = urlparse(url_after)
            url_changed = (
                url_after != url_before
                or old_parsed.fragment != new_parsed.fragment
            )

            logger.info(
                "[Planner]   URL 比较: before=%s | after=%s | fragment: %s -> %s | changed=%s",
                url_before[:80], url_after[:80],
                old_parsed.fragment[:40] if old_parsed.fragment else '(none)',
                new_parsed.fragment[:40] if new_parsed.fragment else '(none)',
                url_changed,
            )

            if url_changed and url_after:
                logger.info("[Planner]   SPA 路由跳转成功: %s", url_after[:80])
                await self._restore_page_state(original_url, parent_nav_steps)
                return url_after, list(parent_nav_steps or [])

            dom_sig_after = await self._get_dom_signature()
            logger.info(
                "[Planner]   DOM 签名比较: before=%s | after=%s | changed=%s",
                dom_sig_before[:16] if dom_sig_before else '(empty)',
                dom_sig_after[:16] if dom_sig_after else '(empty)',
                dom_sig_before != dom_sig_after if (dom_sig_before and dom_sig_after) else 'N/A',
            )
            if dom_sig_after and dom_sig_after != dom_sig_before:
                logger.info(
                    "[Planner]   URL 未变但 DOM 内容已更新（纯 Ajax SPA），使用原始 URL"
                )
                child_nav_steps = list(parent_nav_steps or []) + [nav_step_record]
                await self._restore_page_state(original_url, parent_nav_steps)
                return url_before, child_nav_steps

            logger.info("[Planner]   模拟点击后 URL 和 DOM 均未发生显著变化")

        except Exception as e:
            logger.debug("[Planner]   模拟点击导航 mark_id=%d 失败: %s", mark_id, e)
            await self._restore_page_state(original_url, parent_nav_steps)

        return "", list(parent_nav_steps or [])

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
        return self._artifacts.build_plan(subtasks)

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
        """将 DFS 发现过程写成层次化的 Markdown 知识文档。

        文档结构反映 DFS 遍历的树形层级，每个节点记录：
        - URL、页面类型
        - LLM 的自由观察（observations）

        该文档会被 SkillSedimenter 读取，作为生成 Site Skill 的上下文。
        """
        self._artifacts.write_knowledge_doc(self._knowledge_entries, plan)

    def _sediment_draft_skill(self, plan: TaskPlan) -> None:
        """DFS 完成后立即生成 draft Skill，不等 Worker 执行。

        draft Skill 只包含站点结构和 DFS 观察，没有 XPath 等执行数据。
        为避免当前运行中的 Skill 发现链路读取到草稿，先写入 output/draft_skills；
        后续由 Pipeline 收尾阶段再决定是否提升到 .agents/skills。
        """
        self._artifacts.sediment_draft_skill(self._knowledge_entries, plan)
