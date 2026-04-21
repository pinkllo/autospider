"""详情页 URL 在线收集器：LLM 样本采集 -> 规则生成 -> 规则验证 -> 规则执行。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from autospider.platform.config.runtime import config
from autospider.platform.llm.decider import LLMDecider
from autospider.platform.observability.logger import get_logger
from autospider.platform.browser.som import (
    capture_screenshot_with_marks,
    clear_overlay,
    inject_and_scan,
)
from autospider.platform.persistence.files.idempotent_io import (
    write_json_idempotent,
    write_text_if_changed,
)
from autospider.contexts.collection.application.use_cases.explore_site import (
    build_detail_visit,
    extract_mark_id_text_map,
    prepare_explore_skill_context,
    resolve_selected_mark_ids,
)
from autospider.contexts.collection.infrastructure.adapters.scrapy_generator import (
    ScriptGenerator,
)
from autospider.contexts.collection.infrastructure.repositories.config_repository import (
    CollectionConfig,
    ConfigPersistence,
)
from autospider.contexts.experience.application.use_cases.skill_runtime import SkillRuntime
from autospider.contexts.experience.infrastructure.repositories.skill_repository import (
    SkillRepository as ExperienceSkillRepository,
)
from autospider.contexts.collection.infrastructure.crawler.base.base_collector import BaseCollector
from autospider.contexts.collection.infrastructure.crawler.collector import (
    CommonPattern,
    DetailPageVisit,
    LLMDecisionMaker,
    NavigationHandler,
    URLCollectorResult,
    XPathExtractor,
    smart_scroll,
)

if TYPE_CHECKING:
    from playwright.async_api import Page

    from autospider.contexts.collection.infrastructure.channel.base import URLChannel
    from autospider.platform.shared_kernel.types import SoMSnapshot


logger = get_logger(__name__)
URL_RULE_MIN_PRECISION = 0.8
URL_RULE_MIN_RECALL = 0.8
URL_RULE_MIN_SAMPLE = 3


class URLCollector(BaseCollector):
    """单链路 URL 收集器。"""

    def __init__(
        self,
        page: "Page",
        list_url: str,
        task_description: str,
        execution_brief: dict | None = None,
        explore_count: int = 3,
        max_nav_steps: int = 10,
        target_url_count: int | None = None,
        max_pages: int | None = None,
        output_dir: str = "output",
        url_channel: "URLChannel | None" = None,
        persist_progress: bool = True,
        skill_runtime: SkillRuntime | None = None,
        selected_skills_context: str = "",
        selected_skills: list[dict] | None = None,
        initial_nav_steps: list[dict] | None = None,
        decision_context: dict | None = None,
    ):
        super().__init__(
            page=page,
            list_url=list_url,
            task_description=task_description,
            execution_brief=execution_brief,
            output_dir=output_dir,
            url_channel=url_channel,
            target_url_count=target_url_count,
            max_pages=max_pages,
            persist_progress=persist_progress,
        )

        self.explore_count = explore_count
        self.max_nav_steps = max_nav_steps
        self.skill_runtime = skill_runtime or SkillRuntime(ExperienceSkillRepository())
        self.selected_skills_context = str(selected_skills_context or "")
        self.selected_skills = list(selected_skills or [])
        self.initial_nav_steps = list(initial_nav_steps or [])
        self.decision_context = dict(decision_context or {})

        self.detail_visits: list[DetailPageVisit] = []
        self.step_index = 0
        self.visited_detail_urls: set[str] = set()
        self.common_pattern: CommonPattern | None = None

        self.decider = LLMDecider()
        self.script_generator = ScriptGenerator(output_dir)
        self.config_persistence = ConfigPersistence(output_dir)
        self.xpath_extractor = XPathExtractor()

    async def run(self) -> URLCollectorResult:
        logger.info("\n[URLCollector] ===== 开始在线收集详情页 URL =====")
        logger.info(f"[URLCollector] 任务描述: {self.task_description}")
        logger.info(f"[URLCollector] 列表页: {self.list_url}")
        logger.info(f"[URLCollector] 样本目标: {self.explore_count}")
        await self._prepare_skill_context()

        await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1)
        self._initialize_handlers()

        if self.initial_nav_steps:
            logger.info("\n[Phase 1] 重放 planner 导航路径...")
            nav_success = await self.navigation_handler.replay_nav_steps(self.initial_nav_steps)
            replay_succeeded = (
                bool(getattr(nav_success, "success"))
                if getattr(nav_success, "success", None) is not None
                else bool(nav_success)
            )
            if not replay_succeeded:
                failure_reason = str(getattr(nav_success, "failure_reason", "") or "").strip()
                if failure_reason:
                    raise RuntimeError(f"planner_nav_steps_replay_failed:{failure_reason}")
                raise RuntimeError("planner_nav_steps_replay_failed")
            self.nav_steps = list(self.initial_nav_steps)
            logger.info("[URLCollector] ✓ planner 导航路径重放完成，共 %s 步", len(self.nav_steps))
        else:
            logger.info("\n[Phase 1] 导航阶段：根据任务描述进行筛选操作...")
            nav_success = await self.navigation_handler.run_navigation_phase()
            if not nav_success:
                logger.info("[URLCollector] 导航阶段未完全完成，将在当前页面继续采集")
            self.nav_steps = self.navigation_handler.nav_steps

        if self.navigation_handler and self.navigation_handler.page is not self.page:
            new_page = self.navigation_handler.page
            new_list_url = self.navigation_handler.list_url or new_page.url
            self._sync_page_references(new_page, list_url=new_list_url)

        validation_pages = max(1, int(config.field_extractor.validate_count))

        while self.pagination_handler.current_page_num <= self.max_pages:
            logger.info(
                "\n[Phase 2] manual_sample: 第 %s 页，已收集 %s 条 URL",
                self.pagination_handler.current_page_num,
                len(self.collected_urls),
            )

            page_urls, new_visits = await self._collect_current_page_with_llm()
            if new_visits:
                logger.info("[URLCollector] 本页新增样本 %s 条", len(new_visits))

            self.save_running_progress()

            if len(self.collected_urls) >= self.target_url_count:
                logger.info("[URLCollector] 已达到目标 URL 数量")
                break

            if len(self.detail_visits) >= self.explore_count and not self.common_detail_xpath:
                logger.info("\n[Phase 3] build_rule: 从真实样本生成公共详情 XPath")
                candidate_xpath = self.xpath_extractor.extract_common_xpath(self.detail_visits)
                if candidate_xpath:
                    self.common_detail_xpath = candidate_xpath
                    self.common_pattern = CommonPattern(
                        xpath_pattern=candidate_xpath,
                        confidence=0.8,
                        source_visits=self.detail_visits,
                    )

                    logger.info("\n[Phase 4] validate_rule: 使用后续页面验证公共详情 XPath")
                    validated = await self._validate_xpath_rule_on_next_pages(validation_pages)
                    if validated:
                        logger.info("[URLCollector] 公共详情 XPath 验证通过，切换到规则执行")
                        logger.info("\n[Phase 4.1] 提取分页控件 XPath...")
                        pagination_xpath = await self.pagination_handler.extract_pagination_xpath()
                        if pagination_xpath:
                            logger.info("[URLCollector] ✓ 分页控件 XPath: %s", pagination_xpath)
                        jump_widget_xpath = (
                            await self.pagination_handler.extract_jump_widget_xpath()
                        )
                        if jump_widget_xpath:
                            logger.info("[URLCollector] ✓ 跳转控件已提取")
                        self._save_config()
                        break

                    logger.info("[URLCollector] 公共详情 XPath 验证失败，继续手动采集样本")
                    self.common_detail_xpath = None
                    self.common_pattern = None

            if not await self._advance_to_next_page():
                logger.info("[URLCollector] 无法继续翻页，结束手动采集")
                break

        if self.common_detail_xpath and len(self.collected_urls) < self.target_url_count:
            logger.info("\n[Phase 5] rule_run: 使用公共 XPath 批量收集剩余 URL")
            await self._collect_phase_with_xpath()

        crawler_script = await self._generate_crawler_script()
        result = self._create_result()
        await self._save_result(result, crawler_script)
        self.save_progress_status(status="COMPLETED")
        return result

    def _initialize_handlers(self) -> None:
        self.llm_decision_maker = LLMDecisionMaker(
            page=self.page,
            decider=self.decider,
            task_description=self.task_description,
            collected_urls=self.collected_urls,
            visited_detail_urls=self.visited_detail_urls,
            list_url=self.list_url,
            selected_skills_context=self.selected_skills_context,
            selected_skills=self.selected_skills,
            execution_brief=self.execution_brief,
            decision_context=self.decision_context,
        )
        super()._initialize_handlers()
        self.navigation_handler = NavigationHandler(
            page=self.page,
            list_url=self.list_url,
            task_description=self.task_description,
            max_nav_steps=self.max_nav_steps,
            decider=self.decider,
            execution_brief=self.execution_brief,
            decision_context=self.decision_context,
            screenshots_dir=self.screenshots_dir,
        )

    async def _prepare_skill_context(self) -> None:
        self.selected_skills, self.selected_skills_context = await prepare_explore_skill_context(
            skill_runtime=self.skill_runtime,
            phase="url_collector",
            url=self.list_url,
            task_context={
                "task_description": self.task_description,
                "target_url_count": self.target_url_count,
            },
            llm=self.decider.llm,
            preselected_skills=self.selected_skills,
        )

    async def _collect_current_page_with_llm(self) -> tuple[list[str], list[DetailPageVisit]]:
        if not self.llm_decision_maker:
            return [], []

        target_url_count = self.target_url_count
        max_scrolls = config.url_collector.max_scrolls
        no_new_threshold = config.url_collector.no_new_url_threshold
        page_urls: list[str] = []
        page_visits: list[DetailPageVisit] = []
        scroll_count = 0
        no_new_urls_count = 0
        last_url_count = len(self.collected_urls)

        while scroll_count < max_scrolls and no_new_urls_count < no_new_threshold:
            if len(self.collected_urls) >= target_url_count:
                break

            await clear_overlay(self.page)
            snapshot = await inject_and_scan(self.page)
            _, screenshot_base64 = await capture_screenshot_with_marks(self.page)
            llm_decision = await self.llm_decision_maker.ask_for_decision(
                snapshot, screenshot_base64
            )

            if llm_decision and llm_decision.get("action") == "select":
                args = (
                    llm_decision.get("args") if isinstance(llm_decision.get("args"), dict) else {}
                )
                purpose = (args.get("purpose") or "").lower()
                if purpose in {"detail_links", "detail_link", "detail"}:
                    page_urls_delta, visits_delta = await self._collect_selected_detail_links(
                        llm_decision=llm_decision,
                        snapshot=snapshot,
                    )
                    page_urls.extend(page_urls_delta)
                    page_visits.extend(visits_delta)

            current_count = len(self.collected_urls)
            if current_count == last_url_count:
                no_new_urls_count += 1
            else:
                no_new_urls_count = 0
                last_url_count = current_count

            if len(self.collected_urls) >= target_url_count:
                break
            if not await smart_scroll(self.page):
                break
            scroll_count += 1

        return page_urls, page_visits

    async def _collect_selected_detail_links(
        self,
        *,
        llm_decision: dict,
        snapshot: "SoMSnapshot",
    ) -> tuple[list[str], list[DetailPageVisit]]:
        args = llm_decision.get("args") if isinstance(llm_decision.get("args"), dict) else {}
        items = args.get("items") or []
        mark_id_text_map = extract_mark_id_text_map(items) or args.get("mark_id_text_map", {}) or {}
        fallback_mark_ids = args.get("mark_ids", [])
        mark_ids = await resolve_selected_mark_ids(
            page=self.page,
            llm=self.decider.llm,
            snapshot=snapshot,
            mark_id_text_map=mark_id_text_map,
            fallback_mark_ids=fallback_mark_ids,
        )

        if not mark_ids:
            return [], []

        page_urls: list[str] = []
        page_visits: list[DetailPageVisit] = []
        candidates = [mark for mark in snapshot.marks if mark.mark_id in mark_ids]
        for candidate in candidates:
            if len(self.collected_urls) >= self.target_url_count:
                break

            url = await self.url_extractor.extract_from_element(
                candidate,
                snapshot,
                nav_steps=self.nav_steps,
            )
            if not url:
                continue

            if url not in self.collected_urls:
                if await self.remember_collected_url(url):
                    page_urls.append(url)

            if url in self.visited_detail_urls:
                continue

            visit = build_detail_visit(
                list_url=self.list_url,
                detail_url=url,
                step_index=self.step_index,
                element=candidate,
            )
            self.step_index += 1
            self.detail_visits.append(visit)
            self.visited_detail_urls.add(url)
            page_visits.append(visit)

        return page_urls, page_visits

    async def _preview_urls_with_xpath(self) -> list[str]:
        if not self.common_detail_xpath:
            return []

        preview_urls: list[str] = []
        locators = self.page.locator(f"xpath={self.common_detail_xpath}")
        count = await locators.count()
        for index in range(count):
            locator = locators.nth(index)
            if self.url_extractor:
                url = await self.url_extractor.extract_from_locator(locator, self.nav_steps)
                if url:
                    preview_urls.append(url)

        normalized: list[str] = []
        seen: set[str] = set()
        for url in preview_urls:
            value = str(url or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        return normalized

    async def _validate_xpath_rule_on_next_pages(self, validation_pages: int) -> bool:
        for page_index in range(validation_pages):
            llm_urls, _ = await self._collect_current_page_with_llm()
            xpath_urls = await self._preview_urls_with_xpath()
            llm_set = self._normalize_url_set(llm_urls)
            xpath_set = self._normalize_url_set(xpath_urls)
            if len(llm_set) < URL_RULE_MIN_SAMPLE:
                logger.info(
                    "[URLCollector] XPath 验证样本不足: page=%s, sample=%s, reason=insufficient_validation_sample",
                    page_index + 1,
                    len(llm_set),
                )
                return False
            precision, recall = self._measure_url_rule_quality(llm_set=llm_set, xpath_set=xpath_set)
            if precision < URL_RULE_MIN_PRECISION or recall < URL_RULE_MIN_RECALL:
                logger.info(
                    "[URLCollector] 验证失败: page=%s, llm=%s, xpath=%s, precision=%.3f, recall=%.3f",
                    page_index + 1,
                    len(llm_set),
                    len(xpath_set),
                    precision,
                    recall,
                )
                return False

            self.save_running_progress()
            if page_index == validation_pages - 1:
                break
            if not await self._advance_to_next_page():
                return False

        return True

    def _normalize_url_set(self, urls: list[str]) -> set[str]:
        normalized: set[str] = set()
        for raw in urls:
            value = str(raw or "").strip()
            if value:
                normalized.add(value)
        return normalized

    def _measure_url_rule_quality(
        self, *, llm_set: set[str], xpath_set: set[str]
    ) -> tuple[float, float]:
        if not llm_set or not xpath_set:
            return 0.0, 0.0
        overlap = len(llm_set & xpath_set)
        precision = overlap / len(xpath_set) if xpath_set else 0.0
        recall = overlap / len(llm_set) if llm_set else 0.0
        return precision, recall

    async def _advance_to_next_page(self) -> bool:
        delay = self.rate_controller.get_delay()
        await asyncio.sleep(delay)
        return await self.pagination_handler.find_and_click_next_page()

    def _save_config(self) -> None:
        collection_config = CollectionConfig(
            nav_steps=self.nav_steps,
            common_detail_xpath=self.common_detail_xpath,
            pagination_xpath=(
                self.pagination_handler.pagination_xpath if self.pagination_handler else None
            ),
            jump_widget_xpath=(
                self.pagination_handler.jump_widget_xpath if self.pagination_handler else None
            ),
            list_url=self.list_url,
            task_description=self.task_description,
        )
        self.config_persistence.save(collection_config)
        logger.info("[URLCollector] 配置已持久化")

    async def _generate_crawler_script(self) -> str:
        detail_visits_dict = [
            {
                "detail_page_url": visit.detail_page_url,
                "clicked_element_tag": visit.clicked_element_tag,
                "clicked_element_text": visit.clicked_element_text,
                "clicked_element_href": visit.clicked_element_href,
                "clicked_element_role": visit.clicked_element_role,
                "clicked_element_xpath_candidates": visit.clicked_element_xpath_candidates,
            }
            for visit in self.detail_visits
        ]

        return await self.script_generator.generate_scrapy_playwright_script(
            list_url=self.list_url,
            task_description=self.task_description,
            detail_visits=detail_visits_dict,
            nav_steps=self.nav_steps,
            collected_urls=self.collected_urls,
            common_detail_xpath=self.common_detail_xpath,
        )

    def _create_result(self) -> URLCollectorResult:
        return URLCollectorResult(
            detail_visits=self.detail_visits,
            common_pattern=self.common_pattern,
            collected_urls=self.collected_urls,
            list_page_url=self.list_url,
            task_description=self.task_description,
            created_at="",
        )

    async def _save_result(self, result: URLCollectorResult, crawler_script: str = "") -> None:
        output_file = self.output_dir / "collected_urls.json"
        data = {
            "list_page_url": result.list_page_url,
            "task_description": result.task_description,
            "collected_urls": result.collected_urls,
            "nav_steps": self.nav_steps,
            "detail_visits": [
                {
                    "list_page_url": visit.list_page_url,
                    "detail_page_url": visit.detail_page_url,
                    "clicked_element_tag": visit.clicked_element_tag,
                    "clicked_element_text": visit.clicked_element_text,
                    "clicked_element_href": visit.clicked_element_href,
                    "clicked_element_role": visit.clicked_element_role,
                    "clicked_element_xpath_candidates": visit.clicked_element_xpath_candidates,
                }
                for visit in result.detail_visits
            ],
            "created_at": result.created_at,
        }

        persisted = write_json_idempotent(
            output_file,
            data,
            identity_keys=("list_page_url", "task_description"),
        )
        result.created_at = str((persisted or data).get("created_at") or result.created_at)
        logger.info(f"[Save] 结果已保存到: {output_file}")

        self.url_publish_service.write_snapshot(result.collected_urls)

        if crawler_script:
            script_file = self.output_dir / "spider.py"
            write_text_if_changed(script_file, crawler_script)
            logger.info(f"[Save] Scrapy 爬虫脚本已保存到: {script_file}")


async def collect_detail_urls(
    page: "Page",
    list_url: str,
    task_description: str,
    explore_count: int = 3,
    target_url_count: int | None = None,
    max_pages: int | None = None,
    output_dir: str = "output",
    persist_progress: bool = True,
    skill_runtime: SkillRuntime | None = None,
    selected_skills: list[dict] | None = None,
) -> URLCollectorResult:
    collector = URLCollector(
        page=page,
        list_url=list_url,
        task_description=task_description,
        explore_count=explore_count,
        target_url_count=target_url_count,
        max_pages=max_pages,
        output_dir=output_dir,
        persist_progress=persist_progress,
        skill_runtime=skill_runtime,
        selected_skills=selected_skills,
    )
    return await collector.run()
