"""任务规划器 (Task Planner) — 负责分析网站结构并将复杂的采集任务拆分为多个子任务。

该模块的核心逻辑是通过 LLM (语言模型) 结合视觉分析 (结合 SoM 标注的截图)，识别目标网站的导航结构
（如菜单、分类列表、频道入口等），并自动生成一系列独立的子任务。
每个子任务通常对应一个特定的分类或频道的列表页。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ...common.config import config
from ...common.logger import get_logger
from ...common.protocol import parse_json_dict_from_llm
from ...common.som import inject_and_scan, capture_screenshot_with_marks, clear_overlay
from ...common.som.text_first import resolve_single_mark_id
from ...common.types import SubTask, SubTaskStatus, TaskPlan
from ...common.utils.paths import get_prompt_path
from ...common.utils.prompt_template import render_template

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
        """执行完整的规划流程。

        该方法驱动整个分析过程，最终返回一个包含多个子任务的 TaskPlan。

        Returns:
            TaskPlan: 包含子任务列表和元数据的任务计划对象。
        """
        logger.info("[Planner] 开始分析网站结构: %s", self.site_url)

        # 步骤 1: 访问目标网站，等待 DOM 内容加载完成
        await self.page.goto(self.site_url, wait_until="domcontentloaded", timeout=30000)
        # 等待额外的时间以确保动态内容（如异步加载的菜单）渲染出来
        await self.page.wait_for_timeout(2000)
        logger.info("[Planner] 页面已加载: %s", self.page.url)

        # 步骤 2: 注入 SoM 脚本并扫描页面元素，获取标注截图
        snapshot = await inject_and_scan(self.page)
        _, screenshot_base64 = await capture_screenshot_with_marks(self.page)
        # 清除页面上的标注图层，以免干扰后续操作
        await clear_overlay(self.page)

        # 步骤 3: 将截图发送给 LLM 进行视觉分析，识别导航分类
        analysis = await self._analyze_site_structure(screenshot_base64, snapshot)

        if not analysis:
            logger.warning("[Planner] LLM 分析失败或未识别到有效结构，将生成空计划")
            return self._create_empty_plan()

        # 步骤 4: 结合 SoM 快照和 LLM 的解析结果，提取每个子任务的真实 URL
        subtasks = await self._extract_subtask_urls(analysis, snapshot)

        # 步骤 5: 构建 TaskPlan 对象并将其保存到本地文件系统
        plan = self._build_plan(subtasks)
        self._save_plan(plan)

        logger.info("[Planner] 规划完成，识别并生成了 %d 个子任务", len(plan.subtasks))
        return plan

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
        self, analysis: dict, snapshot: object
    ) -> list[SubTask]:
        """根据 LLM 的分析结果，为每个识别出的分类提取真实的列表页 URL。

        此方法采用了多重兜底策略来应对不同架构的网站：
        1. 优先从 SoM 快照的静态属性中查找 href。
        2. 其次通过执行 JavaScript 获取元素的 href 或最近祖先 A 标签的 href。
        3. 针对 SPA（单页应用），采用模拟点击并监控 URL 变化的方式获取。
        4. 如果以上都失效，回退到当前页 URL。

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
                        list_url = urljoin(base_url, mark.href)
                        logger.info("[Planner] [%s] 策略1：从 mark href 获取 URL: %s", name, list_url[:80])
                        break

            # 策略 2: 注入 JavaScript 读取元素的 href（处理一些 mark 注入后可能动态变化的属性）
            if not list_url and mark_id is not None:
                list_url = await self._get_href_by_js(mark_id, base_url)
                if list_url:
                    logger.info("[Planner] [%s] 策略2：从 JS 属性获取 URL: %s", name, list_url[:80])

            # 策略 3: SPA 兜底 — 实际模拟点击该元素，观察浏览器 URL 是否发生跳转
            if not list_url and mark_id is not None:
                list_url = await self._get_url_by_navigation(mark_id, original_url)
                if list_url:
                    logger.info("[Planner] [%s] 策略3：通过 SPA 模拟点击获取 URL: %s", name, list_url[:80])

            # 策略 4: 最终兜底 — 部分 SPA 点击后内部状态改变但 URL 不变。
            # 这种情况下，我们将当前页设为入口，依靠 Worker Agent 在执行时重新执行点击逻辑。
            if not list_url:
                list_url = base_url
                logger.info("[Planner] [%s] 策略4：无法提取到新 URL，回退至当前页面: %s", name, list_url[:80])

            # 创建子任务实体
            subtask = SubTask(
                id=f"category_{idx + 1:02d}",
                name=name,
                list_url=list_url,
                task_description=task_desc,
                priority=idx,
                max_pages=raw.get("estimated_pages"),
            )
            subtasks.append(subtask)

        return subtasks

    async def _get_href_by_js(self, mark_id: int, base_url: str) -> str:
        """通过执行 JavaScript 直接从页面 DOM 元素获取 href 属性。

        Args:
            mark_id: 元素的 SoM 标识。
            base_url: 当前页面 URL，用于拼接相对路径。

        Returns:
            str: 绝对地址 URL，如果未找到则返回空字符串。
        """
        try:
            href = await self.page.evaluate(
                """(markId) => {
                    // 使用 data-som-id 属性定位元素
                    const el = document.querySelector(`[data-som-id="${markId}"]`);
                    if (!el) return null;
                    // 如果元素本身就是 A 标签或有 href 属性
                    if (el.href) return el.href;
                    // 否则查找其最近的父级 A 标签
                    const anchor = el.closest('a');
                    if (anchor && anchor.href) return anchor.href;
                    return null;
                }""",
                mark_id,
            )
            if href:
                return urljoin(base_url, href)
        except Exception as e:
            logger.debug("[Planner] JS 执行获取 mark_id=%d 的 href 失败: %s", mark_id, e)
        return ""

    async def _get_url_by_navigation(self, mark_id: int, original_url: str) -> str:
        """针对 SPA 网站的兜底策略：模拟点击元素并获取目标跳转 URL。

        该过程会：
        1. 记录当前 URL。
        2. 点击目标元素并等待浏览器 URL 状态更新。
        3. 记录跳转后的新 URL。
        4. 为了不破坏规划过程中的页面一致性，会重新导航回原始 URL 并重置 SoM。

        Args:
            mark_id: SoM 标注的 mark_id。
            original_url: 点击前的原始 URL (用于恢复页面)。

        Returns:
            str: 点击跳转后的新 URL；若 URL 未发生变化，则返回空字符串。
        """
        try:
            logger.info("[Planner]   触发模拟点击 mark_id=%d 以识别 SPA 路由跳转...", mark_id)

            url_before = self.page.url
            locator = self.page.locator(f'[data-som-id="{mark_id}"]')
            
            if await locator.count() == 0:
                logger.debug("[Planner]   未找到对应 mark_id=%d 的元素", mark_id)
                return ""

            # 执行点击
            await locator.first.click(timeout=5000)
            # 等待前端路由或服务端渲染完成跳转
            await self.page.wait_for_timeout(2000)

            url_after = self.page.url

            if url_after and url_after != url_before:
                logger.info("[Planner]   SPA 路由跳转成功: %s", url_after[:80])
                # 回退到原页面，保证对下一个分类的识别环境依然是首页
                await self.page.goto(original_url, wait_until="domcontentloaded", timeout=15000)
                await self.page.wait_for_timeout(1500)
                # 因为 DOM 发生了重载，必须重新注入 SoM 标注
                await inject_and_scan(self.page)
                await clear_overlay(self.page)
                return url_after
            else:
                logger.debug("[Planner]   模拟点击后 URL 未发生显著变化")

        except Exception as e:
            logger.debug("[Planner]   模拟点击导航 mark_id=%d 失败: %s", mark_id, e)
            # 异常时尝试恢复至原页面
            try:
                if self.page.url != original_url:
                    await self.page.goto(original_url, wait_until="domcontentloaded", timeout=15000)
                    await self.page.wait_for_timeout(1500)
            except Exception:
                pass

        return ""

    def _build_plan(self, subtasks: list[SubTask]) -> TaskPlan:
        """构造 TaskPlan 响应对象。

        Args:
            subtasks: 提取出的子任务列表。

        Returns:
            TaskPlan: 封装后的计划对象，包含唯一标识符和时间戳。
        """
        now = datetime.now().isoformat()
        plan_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        return TaskPlan(
            plan_id=plan_id,
            original_request=self.user_request,
            site_url=self.site_url,
            subtasks=subtasks,
            total_subtasks=len(subtasks),
            created_at=now,
            updated_at=now,
        )

    def _create_empty_plan(self) -> TaskPlan:
        """当分析失败或 LLM 未产生结果时，返回一个没有任何子任务的空计划。"""
        return self._build_plan([])

    def _save_plan(self, plan: TaskPlan) -> None:
        """将生成的任务计划序列化为 JSON 文件，存储在指定的输出目录中。

        Args:
            plan: 待保存的 TaskPlan 对象。
        """
        output_path = Path(self.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        plan_file = output_path / "task_plan.json"

        # 使用 Pydantic 的 model_dump 导出数据并写入文件
        with open(plan_file, "w", encoding="utf-8") as f:
            json.dump(plan.model_dump(), f, ensure_ascii=False, indent=2)

        logger.info("[Planner] 任务计划已成功持久化至: %s", plan_file)
