"""任务规划器 — 分析网站结构并将大任务拆分为多个子任务。

通过 LLM + 视觉分析网站导航结构（分类菜单、频道列表等），
自动生成多个独立的子任务，每个子任务对应一个分类/频道的列表页。
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
from ...common.types import SubTask, SubTaskStatus, TaskPlan
from ...common.utils.paths import get_prompt_path
from ...common.utils.prompt_template import render_template

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = get_logger(__name__)

PROMPT_TEMPLATE_PATH = get_prompt_path("planner.yaml")


class TaskPlanner:
    """任务规划器：分析网站结构，将大任务拆分为子任务。

    工作流程:
        1. 打开目标网站
        2. SoM 截图 + LLM 视觉分析导航结构
        3. 识别各分类/频道入口，获取对应 URL
        4. 生成 TaskPlan 并持久化
    """

    def __init__(
        self,
        page: "Page",
        site_url: str,
        user_request: str,
        output_dir: str = "output",
    ):
        self.page = page
        self.site_url = site_url
        self.user_request = user_request
        self.output_dir = output_dir

        # 初始化 LLM（优先使用 planner 专用模型，否则用主模型）
        api_key = config.llm.planner_api_key or config.llm.api_key
        api_base = config.llm.planner_api_base or config.llm.api_base
        model = config.llm.planner_model or config.llm.model

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
        """执行规划流程，返回任务计划。

        Returns:
            包含子任务列表的 TaskPlan 对象。
        """
        logger.info("[Planner] 开始分析网站结构: %s", self.site_url)

        # Step 1: 打开网站
        await self.page.goto(self.site_url, wait_until="domcontentloaded", timeout=30000)
        await self.page.wait_for_timeout(2000)
        logger.info("[Planner] 页面已加载: %s", self.page.url)

        # Step 2: 注入 SoM 并截图
        snapshot = await inject_and_scan(self.page)
        _, screenshot_base64 = await capture_screenshot_with_marks(self.page)
        await clear_overlay(self.page)

        # Step 3: LLM 分析网站结构
        analysis = await self._analyze_site_structure(screenshot_base64)

        if not analysis:
            logger.warning("[Planner] LLM 分析失败，生成空计划")
            return self._create_empty_plan()

        # Step 4: 提取各分类的 URL
        subtasks = await self._extract_subtask_urls(analysis, snapshot)

        # Step 5: 生成计划
        plan = self._build_plan(subtasks)
        self._save_plan(plan)

        logger.info("[Planner] 规划完成，共 %d 个子任务", len(plan.subtasks))
        return plan

    async def _analyze_site_structure(self, screenshot_base64: str) -> dict | None:
        """使用 LLM 视觉分析网站导航结构。

        Args:
            screenshot_base64: 带 SoM 标注的截图。

        Returns:
            LLM 返回的分析结果字典，失败时返回 None。
        """
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
            },
        )

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
            logger.info("[Planner] 调用 LLM 分析网站结构...")
            response = await self.llm.ainvoke(messages)
            response_text = response.content

            result = parse_json_dict_from_llm(response_text)
            if result:
                subtask_count = len(result.get("subtasks", []))
                logger.info("[Planner] LLM 识别到 %d 个分类", subtask_count)
                return result

            logger.warning("[Planner] LLM 响应无法解析: %s", str(response_text)[:200])
        except Exception as e:
            logger.error("[Planner] LLM 分析失败: %s", e)

        return None

    async def _extract_subtask_urls(
        self, analysis: dict, snapshot: object
    ) -> list[SubTask]:
        """从 LLM 分析结果中提取子任务列表，并解析各分类的实际 URL。

        对于传统网站，从元素的 href 属性获取 URL。
        对于 SPA 网站（无 href），实际点击元素后记录导航目标 URL。

        Args:
            analysis: LLM 分析结果。
            snapshot: SoM 快照对象。

        Returns:
            子任务列表。
        """
        raw_subtasks = analysis.get("subtasks", [])
        if not raw_subtasks:
            return []

        subtasks: list[SubTask] = []
        base_url = self.page.url
        original_url = self.page.url

        for idx, raw in enumerate(raw_subtasks):
            name = raw.get("name", f"分类_{idx + 1}")
            mark_id = raw.get("mark_id")
            task_desc = raw.get("task_description", f"采集 {name} 分类的数据")

            # 策略 1: 从 snapshot marks 的 href 属性获取 URL
            list_url = ""
            if mark_id is not None and hasattr(snapshot, "marks"):
                for mark in snapshot.marks:
                    if mark.mark_id == mark_id and mark.href:
                        list_url = urljoin(base_url, mark.href)
                        logger.info("[Planner]   从 mark href 获取 URL: %s", list_url[:80])
                        break

            # 策略 2: 通过 JS 读取元素的 href（使用正确的 data-som-id 选择器）
            if not list_url and mark_id is not None:
                list_url = await self._get_href_by_js(mark_id, base_url)

            # 策略 3: SPA 兜底 — 实际点击元素，等待导航，记录新 URL
            if not list_url and mark_id is not None:
                list_url = await self._get_url_by_navigation(mark_id, original_url)

            # 策略 4: 最终兜底 — 有的 SPA 点击 Tab 后根本不改变 url，直接使用当前 URL 作为入口。
            # 依赖后续的 Worker Agent 根据 task_description 自行点击该 Tab。
            if not list_url:
                list_url = base_url
                logger.info("[Planner]   无法提取到新 URL，使用当前页面作为入口: %s", list_url[:80])

            subtask = SubTask(
                id=f"category_{idx + 1:02d}",
                name=name,
                list_url=list_url,
                task_description=task_desc,
                priority=idx,
                max_pages=raw.get("estimated_pages"),
            )
            subtasks.append(subtask)
            logger.info("[Planner]   子任务 #%d: %s -> %s", idx + 1, name, list_url[:80])

        return subtasks

    async def _get_href_by_js(self, mark_id: int, base_url: str) -> str:
        """通过 JS 从 data-som-id 对应元素读取 href 属性。"""
        try:
            href = await self.page.evaluate(
                """(markId) => {
                    const el = document.querySelector(`[data-som-id="${markId}"]`);
                    if (!el) return null;
                    if (el.href) return el.href;
                    const anchor = el.closest('a');
                    if (anchor && anchor.href) return anchor.href;
                    return null;
                }""",
                mark_id,
            )
            if href:
                url = urljoin(base_url, href)
                logger.info("[Planner]   从 JS href 获取 URL: %s", url[:80])
                return url
        except Exception as e:
            logger.debug("[Planner] JS 获取 mark_id=%d href 失败: %s", mark_id, e)
        return ""

    async def _get_url_by_navigation(self, mark_id: int, original_url: str) -> str:
        """SPA 兜底：点击元素后等待页面 URL 变化，然后返回原页面。

        Args:
            mark_id: SoM 标注的 mark_id。
            original_url: 点击前的原始 URL（用于返回）。

        Returns:
            导航后的 URL，失败时返回空字符串。
        """
        try:
            logger.info("[Planner]   尝试点击 mark_id=%d 获取 SPA 导航 URL...", mark_id)

            # 记录点击前的 URL
            url_before = self.page.url

            # 点击元素
            locator = self.page.locator(f'[data-som-id="{mark_id}"]')
            if await locator.count() == 0:
                logger.debug("[Planner]   mark_id=%d 元素不存在", mark_id)
                return ""

            await locator.first.click(timeout=5000)
            # 给 SPA 路由切换一点时间
            await self.page.wait_for_timeout(2000)

            url_after = self.page.url

            if url_after and url_after != url_before:
                logger.info("[Planner]   SPA 导航成功: %s", url_after[:80])
                # 返回原页面
                await self.page.goto(original_url, wait_until="domcontentloaded", timeout=15000)
                await self.page.wait_for_timeout(1500)
                # 重新注入 SoM（因为页面 DOM 已重建）
                await inject_and_scan(self.page)
                await clear_overlay(self.page)
                return url_after
            else:
                logger.debug("[Planner]   点击后 URL 未变化")

        except Exception as e:
            logger.debug("[Planner]   点击导航 mark_id=%d 失败: %s", mark_id, e)
            # 尝试返回原页面
            try:
                await self.page.goto(original_url, wait_until="domcontentloaded", timeout=15000)
                await self.page.wait_for_timeout(1500)
            except Exception:
                pass

        return ""

    def _build_plan(self, subtasks: list[SubTask]) -> TaskPlan:
        """构建 TaskPlan 对象。"""
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
        """创建空计划（分析失败时使用）。"""
        return self._build_plan([])

    def _save_plan(self, plan: TaskPlan) -> None:
        """将计划持久化到 JSON 文件。"""
        output_path = Path(self.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        plan_file = output_path / "task_plan.json"

        with open(plan_file, "w", encoding="utf-8") as f:
            json.dump(plan.model_dump(), f, ensure_ascii=False, indent=2)

        logger.info("[Planner] 计划已保存: %s", plan_file)
