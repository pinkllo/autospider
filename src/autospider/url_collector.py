"""详情页 URL 收集器

实现流程:
1. 探索阶段：进入 N 个不同的详情页，记录每次进入的操作步骤
2. 分析阶段：分析这 N 次操作的共同模式，提取公共脚本
3. 收集阶段：使用公共脚本遍历列表页，收集所有详情页的 URL
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from .browser import ActionExecutor
from .config import config
from .llm import LLMDecider
from .persistence import CollectionConfig, ConfigPersistence
from .script_generator import ScriptGenerator
from .som import (
    build_mark_id_to_xpath_map,
    capture_screenshot_with_marks,
    clear_overlay,
    format_marks_for_llm,
    inject_and_scan,
    set_overlay_visibility,
)
from .types import (
    Action,
    ActionType,
    AgentState,
    ElementMark,
    RunInput,
    SoMSnapshot,
    XPathCandidate,
)

if TYPE_CHECKING:
    from playwright.async_api import Page


# ============================================================================
# 数据结构定义
# ============================================================================


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


# ============================================================================
# URL 收集器
# ============================================================================


class URLCollector:
    """详情页 URL 收集器"""
    
    def __init__(
        self,
        page: "Page",
        list_url: str,
        task_description: str,  # 任务描述，如"收集招标公告详情页"
        explore_count: int = 3,  # 探索几个详情页
        max_nav_steps: int = 10,  # 导航阶段最大步数
        output_dir: str = "output",
    ):
        self.page = page
        self.list_url = list_url
        self.task_description = task_description
        self.explore_count = explore_count
        self.max_nav_steps = max_nav_steps  # 导航阶段最大步数
        
        # 输出目录
        self.output_dir = Path(output_dir)
        self.screenshots_dir = self.output_dir / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        
        # 状态
        self.detail_visits: list[DetailPageVisit] = []
        self.collected_urls: list[str] = []
        self.step_index = 0
        self.nav_steps: list[dict] = []  # 记录导航步骤
        self.common_detail_xpath: str | None = None  # 从探索阶段提取的公共 xpath
        
        # 已访问的详情页 URL（避免重复）
        self.visited_detail_urls: set[str] = set()
        
        # 复用原有的 LLM 决策器和动作执行器
        self.decider = LLMDecider()
        self.executor: ActionExecutor | None = None  # 延迟初始化
        
        # 脚本生成器
        self.script_generator = ScriptGenerator(output_dir)
        
        # 分页状态
        self.current_page_num = 1  # 当前页码
        self.pagination_xpath: str | None = None  # 下一页按钮的 xpath
        
        # 持久化管理器
        self.config_persistence = ConfigPersistence(output_dir)
        
        # 文本 LLM（用于决策）
        self.llm = ChatOpenAI(
            api_key=config.llm.planner_api_key or config.llm.api_key,
            base_url=config.llm.planner_api_base or config.llm.api_base,
            model=config.llm.planner_model or config.llm.model,
            temperature=0.1,
            max_tokens=4096,
        )
    
    async def run(self) -> URLCollectorResult:
        """运行 URL 收集流程"""
        print(f"\n[URLCollector] ===== 开始收集详情页 URL =====")
        print(f"[URLCollector] 任务描述: {self.task_description}")
        print(f"[URLCollector] 列表页: {self.list_url}")
        print(f"[URLCollector] 将探索 {self.explore_count} 个详情页")
        
        # 1. 导航到列表页
        print(f"\n[Phase 1] 导航到列表页...")
        await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1)
        
        # 初始化动作执行器
        self.executor = ActionExecutor(self.page)
        
        # 2. 导航阶段：让 LLM 根据任务描述先点击筛选条件
        print(f"\n[Phase 2] 导航阶段：根据任务描述进行筛选操作...")
        nav_success = await self._navigation_phase()
        if not nav_success:
            print(f"[Warning] 导航阶段未能完成筛选，将直接在当前页面探索")
        
        # 3. 探索阶段：进入多个详情页
        print(f"\n[Phase 3] 探索阶段：进入 {self.explore_count} 个详情页...")
        await self._explore_phase()
        
        if len(self.detail_visits) < 2:
            print(f"[Warning] 只探索到 {len(self.detail_visits)} 个详情页，需要至少 2 个才能提取模式")
            return URLCollectorResult(
                detail_visits=self.detail_visits,
                list_page_url=self.list_url,
                task_description=self.task_description,
                created_at=datetime.now().isoformat(),
            )
        
        # 3.5 从探索记录中提取公共 xpath
        print(f"\n[Phase 3.5] 提取公共 xpath...")
        self.common_detail_xpath = self._extract_common_xpath()
        if self.common_detail_xpath:
            print(f"[Phase 3.5] ✓ 提取到公共 xpath: {self.common_detail_xpath}")
        else:
            print(f"[Phase 3.5] ⚠ 未能提取公共 xpath，将使用 LLM 收集")
        
        # 3.6 提取分页控件的 xpath
        print(f"\n[Phase 3.6] 提取分页控件 xpath...")
        await self._extract_pagination_xpath()
        if self.pagination_xpath:
            print(f"[Phase 3.6] ✓ 提取到分页控件 xpath: {self.pagination_xpath}")
        else:
            print(f"[Phase 3.6] ⚠ 未找到分页控件，将只收集当前页")
        
        # 4. 收集阶段：使用公共 xpath 遍历列表页收集所有 URL
        if self.common_detail_xpath:
            print(f"\n[Phase 4] 收集阶段：使用公共 xpath 遍历列表页收集所有 URL...")
            await self._collect_phase_with_xpath()
        else:
            print(f"\n[Phase 4] 收集阶段：LLM 遍历列表页收集所有 URL...")
            await self._collect_phase_with_llm()
        
        # 4.5 持久化配置阶段：保存 nav_steps 和 common_detail_xpath
        print(f"\n[Phase 4.5] 持久化配置阶段：保存导航步骤和详情页 xpath...")
        collection_config = CollectionConfig(
            nav_steps=self.nav_steps,
            common_detail_xpath=self.common_detail_xpath,
            pagination_xpath=self.pagination_xpath,
            list_url=self.list_url,
            task_description=self.task_description,
        )
        self.config_persistence.save(collection_config)
        print(f"[Phase 4.5] ✓ 配置已持久化")
        
        # 5. 脚本生成阶段：直接使用 xpath 生成爬虫脚本
        print(f"\n[Phase 5] 脚本生成阶段：使用提取的 xpath 生成爬虫脚本...")
        crawler_script = await self._generate_crawler_script()
        
        # 5. 生成结果
        result = URLCollectorResult(
            detail_visits=self.detail_visits,
            common_pattern=None,  # 不再提取模式
            collected_urls=self.collected_urls,
            list_page_url=self.list_url,
            task_description=self.task_description,
            created_at=datetime.now().isoformat(),
        )
        
        print(f"\n[Complete] 收集完成!")
        print(f"  - 探索了 {len(self.detail_visits)} 个详情页")
        print(f"  - 收集到 {len(self.collected_urls)} 个详情页 URL")
        
        # 保存结果
        await self._save_result(result, crawler_script)
        
        return result
    
    async def _generate_crawler_script(self) -> str:
        """使用脚本生成器生成 Scrapy + scrapy-playwright 爬虫脚本"""
        # 准备数据
        detail_visits_dict = [
            {
                "detail_page_url": v.detail_page_url,
                "clicked_element_tag": v.clicked_element_tag,
                "clicked_element_text": v.clicked_element_text,
                "clicked_element_href": v.clicked_element_href,
                "clicked_element_role": v.clicked_element_role,
                "clicked_element_xpath_candidates": v.clicked_element_xpath_candidates,
            }
            for v in self.detail_visits
        ]
        
        # 调用脚本生成器（传入公共 xpath）
        return await self.script_generator.generate_scrapy_playwright_script(
            list_url=self.list_url,
            task_description=self.task_description,
            detail_visits=detail_visits_dict,
            nav_steps=self.nav_steps,
            collected_urls=self.collected_urls,
            common_detail_xpath=self.common_detail_xpath,
        )
    
    async def _navigation_phase(self) -> bool:
        """
        导航阶段：让 LLM 根据任务描述进行筛选操作
        
        复用原有的 LLM 决策器，点击筛选条件（如"已中标"、"交通运输"等）
        
        Returns:
            是否成功完成导航
        """
        # 设置决策器的任务计划
        self.decider.task_plan = f"""任务分析: 你需要先在列表页进行筛选操作，达到以下目标：
{self.task_description}

执行步骤:
1. 观察页面上的筛选条件（标签、下拉框、勾选框等）
2. 根据任务描述，点击相关的筛选条件
3. 等待页面刷新显示筛选后的结果
4. 当筛选条件都已选择完成后，使用 done 动作

成功标准: 页面显示符合任务描述的筛选结果列表"""

        nav_step = 0
        filter_done = False
        
        while nav_step < self.max_nav_steps and not filter_done:
            nav_step += 1
            print(f"\n[Nav] ----- 导航步骤 {nav_step} -----")
            
            # 1. 观察：注入 SoM 并截图
            try:
                await clear_overlay(self.page)
                await asyncio.sleep(0.2)
                snapshot = await inject_and_scan(self.page)
                screenshot_bytes, screenshot_base64 = await capture_screenshot_with_marks(self.page)
                
                # 保存截图
                screenshot_path = self.screenshots_dir / f"nav_{nav_step:03d}.png"
                screenshot_path.write_bytes(screenshot_bytes)
                
                # 构建 mark_id -> xpath 映射
                mark_id_to_xpath = build_mark_id_to_xpath_map(snapshot)
                marks_text = format_marks_for_llm(snapshot)
                
                print(f"[Nav] 发现 {len(snapshot.marks)} 个可交互元素")
            except Exception as e:
                print(f"[Nav] 观察失败: {e}")
                break
            
            # 2. 决策：调用 LLM
            try:
                # 构建简化的 AgentState
                agent_state = AgentState(
                    input=RunInput(
                        start_url=self.list_url,
                        task=f"筛选操作: {self.task_description}",
                        target_text="筛选完成",
                    ),
                    step_index=nav_step,
                    page_url=self.page.url,
                    page_title=await self.page.title(),
                )
                
                # 解析滚动信息
                scroll_info = None
                if snapshot.scroll_info:
                    from .types import ScrollInfo
                    scroll_info = snapshot.scroll_info
                
                # 调用 LLM 决策
                action = await self.decider.decide(
                    agent_state,
                    screenshot_base64,
                    marks_text,
                    target_found_in_page=False,
                    scroll_info=scroll_info,
                )
                
                print(f"[Nav] LLM 决策: {action.action.value}")
                print(f"[Nav] 思考: {action.thinking[:150] if action.thinking else 'N/A'}...")
                if action.mark_id:
                    print(f"[Nav] 目标元素: [{action.mark_id}] {action.target_text or ''}")
            except Exception as e:
                print(f"[Nav] 决策失败: {e}")
                break
            
            # 3. 执行动作
            if action.action == ActionType.DONE:
                print(f"[Nav] 筛选操作完成")
                filter_done = True
                break
            
            if action.action == ActionType.RETRY:
                print(f"[Nav] 重试")
                continue
            
            try:
                # 隐藏覆盖层
                await set_overlay_visibility(self.page, False)
                
                # 执行动作
                result, script_step = await self.executor.execute(
                    action,
                    mark_id_to_xpath,
                    nav_step,
                )
                
                print(f"[Nav] 执行结果: {'成功' if result.success else '失败'}")
                if result.error:
                    print(f"[Nav] 错误: {result.error}")
                
                # 获取被点击元素的详细信息
                clicked_element = None
                if action.mark_id:
                    clicked_element = next((m for m in snapshot.marks if m.mark_id == action.mark_id), None)
                
                # 记录导航步骤（包含元素的详细信息）
                nav_step_record = {
                    "step": nav_step,
                    "action": action.action.value,
                    "mark_id": action.mark_id,
                    "target_text": action.target_text,
                    "thinking": action.thinking,
                    "success": result.success,
                }
                
                # 如果有点击元素，添加详细信息
                if clicked_element:
                    nav_step_record.update({
                        "clicked_element_tag": clicked_element.tag,
                        "clicked_element_text": clicked_element.text,
                        "clicked_element_href": clicked_element.href,
                        "clicked_element_role": clicked_element.role,
                        "clicked_element_xpath_candidates": [
                            {"xpath": c.xpath, "priority": c.priority, "strategy": c.strategy}
                            for c in clicked_element.xpath_candidates
                        ],
                    })
                
                self.nav_steps.append(nav_step_record)
                
                # 等待页面响应
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"[Nav] 执行失败: {e}")
                continue
        
        if filter_done:
            print(f"[Nav] ✓ 导航阶段完成，共执行 {nav_step} 步")
            # 等待筛选结果加载
            await asyncio.sleep(1)
            return True
        else:
            print(f"[Nav] ⚠ 导航阶段达到最大步数 {self.max_nav_steps}，继续探索")
            return False
    
    async def _explore_phase(self) -> None:
        """探索阶段：进入多个详情页"""
        explored = 0
        max_attempts = self.explore_count * 5  # 增加尝试次数
        attempts = 0
        
        while explored < self.explore_count and attempts < max_attempts:
            attempts += 1
            print(f"\n[Explore] ===== 尝试 {attempts}/{max_attempts}，已探索 {explored}/{self.explore_count} =====")
            
            # 扫描页面获取可点击元素
            print(f"[Explore] 扫描页面...")
            await clear_overlay(self.page)
            snapshot = await inject_and_scan(self.page)
            screenshot_bytes, screenshot_base64 = await capture_screenshot_with_marks(self.page)
            
            # 保存截图
            screenshot_path = self.screenshots_dir / f"explore_{attempts:03d}.png"
            screenshot_path.write_bytes(screenshot_bytes)
            print(f"[Explore] 截图已保存: {screenshot_path.name}")
            
            # 使用 LLM 决定下一步操作
            print(f"[Explore] 调用 LLM 决策...")
            llm_decision = await self._ask_llm_for_decision(snapshot, screenshot_base64)
            
            if llm_decision is None:
                print(f"[Explore] LLM 决策失败，尝试滚动...")
                await self.page.evaluate("window.scrollBy(0, 500)")
                await asyncio.sleep(0.5)
                continue
            
            decision_type = llm_decision.get("action")
            
            # 情况 1: 当前页面就是详情页
            if decision_type == "current_is_detail":
                current_url = self.page.url
                if current_url not in self.visited_detail_urls:
                    print(f"[Explore] ✓ LLM 判断当前页面就是详情页: {current_url[:60]}...")
                    
                    # 创建访问记录
                    visit = DetailPageVisit(
                        list_page_url=self.list_url,
                        detail_page_url=current_url,
                        clicked_element_mark_id=0,
                        clicked_element_tag="page",
                        clicked_element_text="当前页面",
                        clicked_element_href=current_url,
                        clicked_element_role="page",
                        clicked_element_xpath_candidates=[],
                        step_index=self.step_index,
                        timestamp=datetime.now().isoformat(),
                    )
                    self.detail_visits.append(visit)
                    self.visited_detail_urls.add(current_url)
                    explored += 1
                    self.step_index += 1
                    print(f"[Explore] 已探索 {explored}/{self.explore_count} 个详情页")
                    
                    # 返回列表页继续探索
                    print(f"[Explore] 返回列表页...")
                    await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(1)
                else:
                    print(f"[Explore] 当前页面已访问，滚动查找更多...")
                    await self.page.evaluate("window.scrollBy(0, 500)")
                    await asyncio.sleep(0.5)
                continue
            
            # 情况 2: 选择了详情链接的 mark_ids
            if decision_type == "select_detail_links":
                mark_ids = llm_decision.get("mark_ids", [])
                reasoning = llm_decision.get("reasoning", "")
                print(f"[Explore] LLM 选择了 {len(mark_ids)} 个详情链接: {mark_ids}")
                print(f"[Explore] 理由: {reasoning[:100]}...")
                
                if not mark_ids:
                    print(f"[Explore] 没有选中任何链接，尝试滚动...")
                    await self.page.evaluate("window.scrollBy(0, 500)")
                    await asyncio.sleep(0.5)
                    continue
                
                # 根据 mark_id 获取元素
                print(f"[Explore] 从 {len(snapshot.marks)} 个元素中查找 mark_ids...")
                candidates = [m for m in snapshot.marks if m.mark_id in mark_ids]
                print(f"[Explore] 找到 {len(candidates)} 个候选元素")
                
                # 遍历候选，获取未访问的 URL
                for i, candidate in enumerate(candidates, 1):
                    print(f"[Explore] 处理候选 {i}/{len(candidates)}: [{candidate.mark_id}] {candidate.text[:30]}...")
                    url = await self._extract_url_from_element(candidate, snapshot)
                    if url and url not in self.visited_detail_urls:
                        # 创建访问记录
                        visit = DetailPageVisit(
                            list_page_url=self.list_url,
                            detail_page_url=url,
                            clicked_element_mark_id=candidate.mark_id,
                            clicked_element_tag=candidate.tag,
                            clicked_element_text=candidate.text,
                            clicked_element_href=candidate.href,
                            clicked_element_role=candidate.role,
                            clicked_element_xpath_candidates=[
                                {"xpath": c.xpath, "priority": c.priority, "strategy": c.strategy}
                                for c in candidate.xpath_candidates
                            ],
                            step_index=self.step_index,
                            timestamp=datetime.now().isoformat(),
                        )
                        self.detail_visits.append(visit)
                        self.visited_detail_urls.add(url)
                        explored += 1
                        self.step_index += 1
                        print(f"[Explore] ✓ 获取到详情页 URL: {url[:60]}...")
                        print(f"[Explore] 已探索 {explored}/{self.explore_count} 个详情页")
                        
                        if explored >= self.explore_count:
                            break
                
                # 如果这一轮没有新的 URL，滚动
                if explored < self.explore_count:
                    print(f"[Explore] 滚动查找更多...")
                    await self.page.evaluate("window.scrollBy(0, 500)")
                    await asyncio.sleep(0.5)
                continue
            
            # 情况 3: 需要点击进入详情页
            if decision_type == "click_to_enter":
                mark_id = llm_decision.get("mark_id")
                print(f"[Explore] LLM 要求点击元素 [{mark_id}] 进入详情页")
                
                # 找到元素并点击
                element = next((m for m in snapshot.marks if m.mark_id == mark_id), None)
                if element:
                    url = await self._click_and_get_url(element)
                    if url and url not in self.visited_detail_urls:
                        visit = DetailPageVisit(
                            list_page_url=self.list_url,
                            detail_page_url=url,
                            clicked_element_mark_id=element.mark_id,
                            clicked_element_tag=element.tag,
                            clicked_element_text=element.text,
                            clicked_element_href=element.href,
                            clicked_element_role=element.role,
                            clicked_element_xpath_candidates=[
                                {"xpath": c.xpath, "priority": c.priority, "strategy": c.strategy}
                                for c in element.xpath_candidates
                            ],
                            step_index=self.step_index,
                            timestamp=datetime.now().isoformat(),
                        )
                        self.detail_visits.append(visit)
                        self.visited_detail_urls.add(url)
                        explored += 1
                        self.step_index += 1
                        print(f"[Explore] ✓ 点击后获取到 URL: {url[:60]}...")
                        print(f"[Explore] 已探索 {explored}/{self.explore_count} 个详情页")
                continue
            
            # 其他情况：滚动
            print(f"[Explore] 未知决策类型，滚动...")
            await self.page.evaluate("window.scrollBy(0, 500)")
            await asyncio.sleep(0.5)
    
    async def _ask_llm_for_decision(
        self, 
        snapshot: SoMSnapshot,
        screenshot_base64: str = ""
    ) -> dict | None:
        """让视觉 LLM 决定如何获取详情页 URL"""
        # 重要：这里应该使用视觉 LLM（decider 使用的模型），需要传入截图
        
        current_url = self.page.url
        
        print(f"[LLM] 当前页面: {current_url[:80]}...")
        print(f"[LLM] 可交互元素数量: {len(snapshot.marks)}")
        print(f"[LLM] 截图大小: {len(screenshot_base64)} 字符")
        
        # 构建提示词
        system_prompt = """你是一个网页爬虫专家。你需要帮助用户获取详情页的 URL。

你有以下工具可以使用：

1. **select_detail_links**: 选择页面上的详情链接
   - 只选择列表中**项目标题/公告标题**类的链接
   - 不要选择：筛选标签、分页按钮、导航菜单、"查看更多"等
   - 返回: {"action": "select_detail_links", "mark_ids": [40, 41, 42], "reasoning": "..."}
   - mark_ids 是你认为是详情页链接的元素编号列表

2. **current_is_detail**: 当前页面就是详情页
   - 当你判断当前页面已经是一个详情页（而不是列表页）时使用
   - 返回: {"action": "current_is_detail", "reasoning": "..."}

3. **scroll_down**: 需要滚动查看更多
   - 当前视图没有新的详情链接时使用
   - 返回: {"action": "scroll_down", "reasoning": "..."}

重要提示：
- 只选择**列表项目的标题**，通常是较长的项目名称或公告标题
- 不要选择筛选条件、分类标签、按钮等
- 如果元素文本很短（如"查看"、"详情"等），通常不是标题链接

你只能看到“可交互元素列表”（marks），没有截图。

输出格式：严格 JSON，不要 markdown 代码块。"""
        
        # 已收集的 URL（用于避免重复）
        collected_urls_str = "\n".join([f"- {url}" for url in list(self.collected_urls)[:10]]) if self.collected_urls else "暂无"
        
        user_message = f"""## 任务描述
{self.task_description}

## 当前页面 URL
{current_url}

## 已探索的详情页数量
{len(self.visited_detail_urls)}

## 已收集的 URL 示例（避免重复）
{collected_urls_str}

请观察截图中红色边框标注的元素（每个元素有编号），**只选择列表中的项目标题链接**，不要选择筛选标签或其他按钮。"""
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=[
                {"type": "text", "text": user_message},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_base64}"}},
            ]),
        ]
        
        try:
            print(f"[LLM] 调用视觉 LLM 进行决策...")
            # 使用 decider 的 LLM（视觉模型）
            response = await self.decider.llm.ainvoke(messages)
            response_text = response.content
            print(f"[LLM] 响应前100字符: {response_text[:100]}...")
            
            # 解析 JSON
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                data = json.loads(json_match.group())
                print(f"[LLM] 决策: {data.get('action')}")
                print(f"[LLM] 理由: {data.get('reasoning', 'N/A')[:100]}...")
                return data
            else:
                print(f"[LLM] 响应中未找到 JSON: {response_text[:200]}")
        except json.JSONDecodeError as e:
            print(f"[LLM] JSON 解析失败: {e}")
            print(f"[LLM] 原始响应: {response_text[:300] if 'response_text' in locals() else 'N/A'}")
        except Exception as e:
            print(f"[LLM] 决策失败: {e}")
            import traceback
            traceback.print_exc()
        
        return None
    
    async def _extract_url_from_element(
        self, 
        element: ElementMark,
        snapshot: SoMSnapshot
    ) -> str | None:
        """从元素中提取 URL（优先从 href，否则点击获取）"""
        # 策略 1: 先尝试从 href 提取
        if element.href:
            from urllib.parse import urljoin
            url = urljoin(self.list_url, element.href)
            print(f"[Extract] ✓ 从 href 提取: {url[:60]}...")
            return url
        
        # 策略 2: 点击获取
        print(f"[Extract] 元素无 href，点击获取 URL...")
        return await self._click_and_get_url(element)
    
    async def _click_and_get_url(self, element: ElementMark) -> str | None:
        """点击元素并获取新页面的 URL"""
        list_url = self.page.url
        context = self.page.context
        pages_before = len(context.pages)
        
        print(f"[Click] 当前 URL: {list_url[:60]}...")
        print(f"[Click] 当前标签页数: {pages_before}")
        
        try:
            # 隐藏覆盖层
            await set_overlay_visibility(self.page, False)
            
            # 策略1: 优先使用 data-som-id
            locator = self.page.locator(f'[data-som-id="{element.mark_id}"]')
            element_found = await locator.count() > 0
            
            # 策略2: 如果 data-som-id 失效(DOM更新/滚动导致),使用 XPath 后备
            if not element_found and element.xpath_candidates:
                print(f"[Click] data-som-id失效,尝试XPath后备...")
                # 按优先级尝试xpath
                for candidate in sorted(element.xpath_candidates, key=lambda x: x.priority):
                    try:
                        xpath_locator = self.page.locator(f"xpath={candidate.xpath}")
                        if await xpath_locator.count() > 0:
                            locator = xpath_locator
                            element_found = True
                            print(f"[Click] ✓ XPath成功: {candidate.xpath[:60]}...")
                            break
                    except Exception as e:
                        continue
            
            if element_found:
                print(f"[Click] 点击元素 [{element.mark_id}]...")
                
                # 尝试监听新标签页
                new_page = None
                try:
                    async with context.expect_page(timeout=3000) as new_page_info:
                        await locator.first.click(timeout=5000)
                    
                    # 有新标签页打开
                    new_page = await new_page_info.value
                    await new_page.wait_for_load_state("domcontentloaded", timeout=10000)
                    new_url = new_page.url
                    print(f"[Click] ✓ 检测到新标签页: {new_url[:60]}...")
                    
                    # 关闭新标签页
                    await new_page.close()
                    
                    return new_url
                    
                except Exception as e:
                    # 没有新标签页，可能是当前页面导航
                    print(f"[Click] 未检测到新标签页，检查当前页面 URL...")
                    
                    # 给 SPA 时间更新
                    await asyncio.sleep(3)
                    
                    new_url = self.page.url
                    pages_after = len(context.pages)
                    
                    # 详细比较
                    from urllib.parse import urlparse
                    old_parsed = urlparse(list_url)
                    new_parsed = urlparse(new_url)
                    
                    print(f"[Click] 旧 URL: {list_url}")
                    print(f"[Click] 新 URL: {new_url}")
                    print(f"[Click] 旧 hash: {old_parsed.fragment}")
                    print(f"[Click] 新 hash: {new_parsed.fragment}")
                    print(f"[Click] 标签页数: {pages_before} -> {pages_after}")
                    
                    # 检查是否打开了新标签页（但没被 expect_page 捕获）
                    if pages_after > pages_before:
                        print(f"[Click] 检测到新标签页（延迟打开）")
                        # 获取最新的标签页
                        all_pages = context.pages
                        new_page = all_pages[-1]
                        await new_page.wait_for_load_state("domcontentloaded", timeout=10000)
                        new_url = new_page.url
                        print(f"[Click] ✓ 从新标签页获取 URL: {new_url[:60]}...")
                        
                        # 关闭新标签页
                        await new_page.close()
                        
                        return new_url
                    
                    # 检查 URL 或 hash 是否变化
                    if new_url != list_url:
                        print(f"[Click] ✓ URL 已变化（完整 URL 不同）")
                        
                        # 返回列表页
                        print(f"[Click] 返回列表页...")
                        await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
                        await asyncio.sleep(1)
                        
                        return new_url
                    elif old_parsed.fragment != new_parsed.fragment:
                        print(f"[Click] ✓ URL 已变化（hash 不同）")
                        
                        # 返回列表页
                        print(f"[Click] 返回列表页...")
                        await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
                        await asyncio.sleep(1)
                        
                        return new_url
                    else:
                        print(f"[Click] ✗ URL 未变化")
                        return None
            else:
                print(f"[Click] ✗ 找不到元素 {element.mark_id}")
        except Exception as e:
            print(f"[Click] ✗ 点击失败: {e}")
            # 尝试返回列表页
            try:
                await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
            except:
                pass
        
        return None
    
    async def _click_element_and_get_url(self, element_locator, index: int = 0) -> str | None:
        """点击 playwright 元素并获取新页面的 URL（用于收集阶段）"""
        list_url = self.page.url
        context = self.page.context
        pages_before = len(context.pages)
        
        try:
            # 尝试监听新标签页
            try:
                async with context.expect_page(timeout=3000) as new_page_info:
                    await element_locator.click(timeout=5000)
                
                # 有新标签页打开
                new_page = await new_page_info.value
                await new_page.wait_for_load_state("domcontentloaded", timeout=10000)
                new_url = new_page.url
                
                # 关闭新标签页
                await new_page.close()
                
                return new_url
                
            except Exception as e:
                # 没有新标签页，可能是当前页面导航
                await asyncio.sleep(2)
                
                new_url = self.page.url
                pages_after = len(context.pages)
                
                # 检查是否打开了新标签页（延迟打开）
                if pages_after > pages_before:
                    all_pages = context.pages
                    new_page = all_pages[-1]
                    await new_page.wait_for_load_state("domcontentloaded", timeout=10000)
                    new_url = new_page.url
                    
                    # 关闭新标签页
                    await new_page.close()
                    
                    return new_url
                
                # 检查 URL 或 hash 是否变化
                from urllib.parse import urlparse
                old_parsed = urlparse(list_url)
                new_parsed = urlparse(new_url)
                
                if new_url != list_url or old_parsed.fragment != new_parsed.fragment:
                    # URL 已变化，返回列表页
                    await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(1)
                    
                    # 重新执行导航步骤
                    if self.nav_steps:
                        await self._replay_nav_steps()
                    
                    return new_url
                
                return None
                
        except Exception as e:
            print(f"[Collect-XPath] 点击失败: {e}")
            # 尝试返回列表页
            try:
                await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(1)
                if self.nav_steps:
                    await self._replay_nav_steps()
            except:
                pass
            return None
    
    def _extract_common_xpath(self) -> str | None:
        """
        从探索记录中提取公共 xpath
        
        分析所有 detail_visits 的 xpath_candidates，找出最稳定的公共 xpath 模式
        """
        if len(self.detail_visits) < 2:
            return None
        
        # 收集所有 xpath 候选（按 priority 排序）
        all_xpaths_by_priority: dict[int, list[str]] = {}
        
        for visit in self.detail_visits:
            for candidate in visit.clicked_element_xpath_candidates:
                priority = candidate.get("priority", 99)
                xpath = candidate.get("xpath", "")
                if xpath:
                    if priority not in all_xpaths_by_priority:
                        all_xpaths_by_priority[priority] = []
                    all_xpaths_by_priority[priority].append(xpath)
        
        if not all_xpaths_by_priority:
            return None
        
        # 按 priority 从小到大尝试找公共模式
        for priority in sorted(all_xpaths_by_priority.keys()):
            xpaths = all_xpaths_by_priority[priority]
            
            # 尝试找出公共的 xpath 前缀/模式
            common_xpath = self._find_common_xpath_pattern(xpaths)
            if common_xpath:
                print(f"[XPath] 从 priority={priority} 的 xpath 中找到公共模式")
                return common_xpath
        
        return None
    
    def _find_common_xpath_pattern(self, xpaths: list[str]) -> str | None:
        """
        从一组 xpath 中找出公共模式
        
        例如:
        - //section//ul/li[1]/a -> //section//ul/li/a
        - //section//ul/li[2]/a -> //section//ul/li/a
        """
        if not xpaths:
            return None
        
        import re
        
        # 移除所有 xpath 中的索引 [n]，得到通用模式
        normalized_xpaths = []
        for xpath in xpaths:
            # 移除位置谓词 [1], [2], etc.
            normalized = re.sub(r'\[\d+\]', '', xpath)
            normalized_xpaths.append(normalized)
        
        # 检查是否所有 xpath 都有相同的通用模式
        unique_patterns = set(normalized_xpaths)
        
        if len(unique_patterns) == 1:
            # 所有 xpath 去掉索引后相同
            return list(unique_patterns)[0]
        
        # 尝试找最长公共前缀
        if normalized_xpaths:
            common_prefix = normalized_xpaths[0]
            for xpath in normalized_xpaths[1:]:
                while not xpath.startswith(common_prefix) and common_prefix:
                    # 回退到上一个 /
                    last_slash = common_prefix.rfind('/')
                    if last_slash > 0:
                        common_prefix = common_prefix[:last_slash]
                    else:
                        common_prefix = ""
            
            if common_prefix and len(common_prefix) > 5:
                return common_prefix
        
        return None
    
    async def _extract_pagination_xpath(self) -> None:
        """
        在探索阶段提取分页控件的 xpath
        
        通过扫描页面查找下一页按钮，并记录其 xpath
        """
        print(f"[Extract-Pagination] 开始提取分页控件 xpath...")
        
        # 确保在列表页
        current_url = self.page.url
        if current_url != self.list_url:
            print(f"[Extract-Pagination] 返回列表页...")
            await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1)
            
            # 重新执行导航步骤
            if self.nav_steps:
                await self._replay_nav_steps()
        
        # 常见的下一页按钮选择器（按优先级排列）
        next_page_selectors = [
            # 文字类
            "//a[contains(text(), '下一页')]",
            "//button[contains(text(), '下一页')]",
            "//span[contains(text(), '下一页')]/parent::*",
            "//a[contains(text(), '下页')]",
            "//a[text()='>>']",
            "//a[text()='>']",
            "//button[text()='>>']",
            "//button[text()='>']",
            # class 类
            "//a[contains(@class, 'next')]",
            "//button[contains(@class, 'next')]",
            "//li[contains(@class, 'next')]/a",
            "//li[contains(@class, 'next')]/button",
            "//*[contains(@class, 'pagination-next')]//a",
            "//*[contains(@class, 'pagination-next')]//button",
            "//*[contains(@class, 'pagination-next')]",
            # aria-label 类
            "//*[@aria-label='下一页']",
            "//*[@aria-label='Next']",
            "//*[@aria-label='next']",
            "//a[@aria-label='下一页']",
            "//button[@aria-label='下一页']",
            # title 类
            "//a[@title='下一页']",
            "//button[@title='下一页']",
            # ant-design 分页
            "//li[contains(@class, 'ant-pagination-next')]/button",
            "//li[contains(@class, 'ant-pagination-next')]/a",
            # element-ui 分页
            "//button[contains(@class, 'btn-next')]",
            # 通用 next class
            "//*[contains(@class, 'next') and (self::a or self::button)]",
        ]
        
        # 先滚动到页面底部，分页控件通常在底部
        print(f"[Extract-Pagination] 滚动到页面底部查找分页控件...")
        await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1)
        
        # 遍历选择器查找
        for selector in next_page_selectors:
            try:
                locator = self.page.locator(f"xpath={selector}")
                count = await locator.count()
                
                if count > 0:
                    element = locator.first
                    
                    # 检查元素是否可见
                    if not await element.is_visible():
                        continue
                    
                    # 检查是否已禁用（如果禁用说明可能只有一页）
                    is_disabled = await element.get_attribute("disabled")
                    class_attr = await element.get_attribute("class") or ""
                    aria_disabled = await element.get_attribute("aria-disabled")
                    
                    if is_disabled or "disabled" in class_attr or aria_disabled == "true":
                        print(f"[Extract-Pagination] 找到分页按钮但已禁用: {selector}")
                        # 禁用的也记录，因为后续页可能会启用
                        self.pagination_xpath = selector
                        print(f"[Extract-Pagination] ✓ 记录分页控件 xpath（当前禁用）: {selector}")
                        return
                    
                    # 找到可用的分页按钮
                    self.pagination_xpath = selector
                    print(f"[Extract-Pagination] ✓ 找到分页控件 xpath: {selector}")
                    
                    # 尝试获取元素文本用于确认
                    try:
                        text = await element.text_content()
                        if text:
                            print(f"[Extract-Pagination] 按钮文本: {text.strip()[:20]}")
                    except:
                        pass
                    
                    return
                    
            except Exception as e:
                # 这个选择器不行，继续尝试下一个
                continue
        
        # 如果常规选择器都失败，尝试用 LLM 视觉识别
        print(f"[Extract-Pagination] 常规选择器未找到，尝试 LLM 视觉识别...")
        await self._extract_pagination_xpath_with_llm()
    
    async def _extract_pagination_xpath_with_llm(self) -> None:
        """使用 LLM 视觉识别分页控件并提取 xpath"""
        try:
            # 截图
            await clear_overlay(self.page)
            snapshot = await inject_and_scan(self.page)
            screenshot_bytes, screenshot_base64 = await capture_screenshot_with_marks(self.page)
            
            # 保存截图
            screenshot_path = self.screenshots_dir / "pagination_extract.png"
            screenshot_path.write_bytes(screenshot_bytes)
            
            system_prompt = """你是一个网页爬虫专家。请帮我找到页面上的"下一页"分页按钮。

观察截图中红色边框标注的元素（每个元素有编号），找到分页区域的"下一页"按钮。

返回格式（严格 JSON）：
{"found": true, "mark_id": 123, "reasoning": "在页面底部找到了下一页按钮，编号为123"}
或
{"found": false, "reasoning": "页面没有分页按钮"}

注意：
- 只找"下一页"按钮或">"箭头，不要找页码数字
- 分页按钮通常在页面底部
- 不要返回 markdown 代码块，只返回纯 JSON"""
            
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=[
                    {"type": "text", "text": "请找到下一页按钮的元素编号"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_base64}"}},
                ]),
            ]
            
            response = await self.decider.llm.ainvoke(messages)
            response_text = response.content
            
            # 解析 JSON
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                data = json.loads(json_match.group())
                
                if data.get("found") and data.get("mark_id"):
                    mark_id = data["mark_id"]
                    print(f"[Extract-Pagination-LLM] 找到分页按钮 [{mark_id}]: {data.get('reasoning', '')}")
                    
                    # 找到对应的元素，获取其 xpath
                    element = next((m for m in snapshot.marks if m.mark_id == mark_id), None)
                    if element and element.xpath_candidates:
                        # 取优先级最高的 xpath
                        sorted_candidates = sorted(element.xpath_candidates, key=lambda x: x.priority)
                        best_xpath = sorted_candidates[0].xpath if sorted_candidates else None
                        
                        if best_xpath:
                            self.pagination_xpath = best_xpath
                            print(f"[Extract-Pagination-LLM] ✓ 提取到 xpath: {best_xpath}")
                            return
                else:
                    print(f"[Extract-Pagination-LLM] 未找到分页按钮: {data.get('reasoning', '')}")
        except Exception as e:
            print(f"[Extract-Pagination-LLM] LLM 识别失败: {e}")
        
        print(f"[Extract-Pagination] ⚠ 未能提取分页控件 xpath")
    
    async def _collect_phase_with_xpath(self) -> None:
        """收集阶段：使用公共 xpath 直接提取 URL（无需 LLM），支持多页翻页"""
        if not self.common_detail_xpath:
            print(f"[Collect] 没有公共 xpath，回退到 LLM 收集")
            await self._collect_phase_with_llm()
            return
        
        # 确保回到列表页开始位置
        print(f"[Collect-XPath] 返回列表页开始位置...")
        await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1)
        
        # 重新执行导航步骤（筛选操作）
        if self.nav_steps:
            print(f"[Collect-XPath] 重新执行 {len(self.nav_steps)} 个导航步骤...")
            await self._replay_nav_steps()
        
        max_scrolls = config.url_collector.max_scrolls
        no_new_threshold = config.url_collector.no_new_url_threshold
        target_url_count = config.url_collector.target_url_count
        max_pages = config.url_collector.max_pages  # 最大翻页次数
        
        print(f"[Collect-XPath] 使用 xpath: {self.common_detail_xpath}")
        print(f"[Collect-XPath] 目标：收集 {target_url_count} 个 URL（当前已有 {len(self.collected_urls)} 个）")
        print(f"[Collect-XPath] 最大翻页次数: {max_pages}")
        
        # 重置分页状态
        self.current_page_num = 1
        
        # 外层循环：翻页
        while self.current_page_num <= max_pages:
            print(f"\n[Collect-XPath] ===== 第 {self.current_page_num} 页 =====")
            
            # 检查是否达到目标
            if len(self.collected_urls) >= target_url_count:
                print(f"[Collect-XPath] ✓ 已达到目标数量 {target_url_count}，结束收集")
                break
            
            scroll_count = 0
            last_url_count = len(self.collected_urls)
            no_new_urls_count = 0
            
            # 内层循环：当前页滚动收集
            while scroll_count < max_scrolls and no_new_urls_count < no_new_threshold:
                # 检查是否达到目标
                if len(self.collected_urls) >= target_url_count:
                    print(f"[Collect-XPath] ✓ 已达到目标数量 {target_url_count}，结束收集")
                    break
                
                print(f"\n[Collect-XPath] ----- 第 {self.current_page_num} 页，滚动 {scroll_count + 1}/{max_scrolls} -----")
                
                # 使用 xpath 直接获取元素
                try:
                    elements = await self.page.locator(f"xpath={self.common_detail_xpath}").all()
                    print(f"[Collect-XPath] 找到 {len(elements)} 个匹配元素")
                    
                    for i, element in enumerate(elements):
                        try:
                            # 策略 1: 尝试获取元素自身的 href
                            href = await element.get_attribute("href")
                            
                            # 策略 2: 如果元素本身没有 href，查找内部的 a 标签
                            if not href:
                                try:
                                    a_element = element.locator("a[href]").first
                                    if await a_element.count() > 0:
                                        href = await a_element.get_attribute("href")
                                except:
                                    pass
                            
                            if href:
                                from urllib.parse import urljoin
                                url = urljoin(self.list_url, href)
                                if url not in self.collected_urls:
                                    self.collected_urls.append(url)
                                    print(f"[Collect-XPath] ✓ 从 href 获取: {url[:60]}...")
                            else:
                                # 策略 3: 点击元素并监听新标签页（和 Phase 3 一样）
                                text = (await element.text_content())[:30] if await element.text_content() else 'N/A'
                                print(f"[Collect-XPath] 元素无 href，尝试点击: {text}...")
                                
                                # 点击并获取 URL
                                url = await self._click_element_and_get_url(element, i)
                                if url and url not in self.collected_urls:
                                    self.collected_urls.append(url)
                                    print(f"[Collect-XPath] ✓ 点击获取: {url[:60]}...")
                        except Exception as e:
                            print(f"[Collect-XPath] 处理元素失败: {e}")
                            continue
                            
                except Exception as e:
                    print(f"[Collect-XPath] xpath 查询失败: {e}")
                
                # 检查是否有新 URL
                current_count = len(self.collected_urls)
                if current_count == last_url_count:
                    no_new_urls_count += 1
                    print(f"[Collect-XPath] 连续 {no_new_urls_count} 次无新 URL")
                else:
                    no_new_urls_count = 0
                    print(f"[Collect-XPath] ✓ 当前已收集 {current_count} 个 URL（新增 {current_count - last_url_count} 个）")
                    last_url_count = current_count
                
                # 滚动页面
                await self.page.evaluate("window.scrollBy(0, 500)")
                await asyncio.sleep(0.5)
                scroll_count += 1
            
            # 当前页收集完成，尝试翻页
            if len(self.collected_urls) >= target_url_count:
                break
            
            # 尝试翻页
            page_turned = await self._find_and_click_next_page()
            if not page_turned:
                # 如果常规方法找不到，尝试用 LLM
                await clear_overlay(self.page)
                snapshot = await inject_and_scan(self.page)
                screenshot_bytes, screenshot_base64 = await capture_screenshot_with_marks(self.page)
                page_turned = await self._find_next_page_with_llm(screenshot_base64)
            
            if not page_turned:
                print(f"[Collect-XPath] 无法翻页，结束收集")
                break
        
        print(f"\n[Collect-XPath] 收集完成!")
        print(f"  - 共翻页 {self.current_page_num} 页")
        print(f"  - 收集到 {len(self.collected_urls)} 个 URL")
    
    async def _find_and_click_next_page(self) -> bool:
        """
        查找并点击下一页按钮
        
        优先使用探索阶段提取的 pagination_xpath，如果没有则尝试常见选择器
        
        Returns:
            是否成功翻页
        """
        print(f"\n[Pagination] 尝试翻页...")
        
        # 先滚动到页面底部，分页控件通常在底部
        await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.5)
        
        # 优先使用探索阶段提取的 xpath
        if self.pagination_xpath:
            print(f"[Pagination] 使用已提取的 xpath: {self.pagination_xpath}")
            try:
                locator = self.page.locator(f"xpath={self.pagination_xpath}")
                if await locator.count() > 0:
                    element = locator.first
                    
                    # 检查是否可点击（没有 disabled）
                    is_disabled = await element.get_attribute("disabled")
                    class_attr = await element.get_attribute("class") or ""
                    aria_disabled = await element.get_attribute("aria-disabled")
                    
                    if is_disabled or "disabled" in class_attr or aria_disabled == "true":
                        print(f"[Pagination] 下一页按钮已禁用，已到最后一页")
                        return False
                    
                    # 检查元素是否可见
                    if not await element.is_visible():
                        print(f"[Pagination] 下一页按钮不可见，尝试其他方法...")
                    else:
                        await element.click(timeout=5000)
                        await asyncio.sleep(2)  # 等待页面加载
                        self.current_page_num += 1
                        print(f"[Pagination] ✓ 翻页成功，当前第 {self.current_page_num} 页")
                        return True
            except Exception as e:
                print(f"[Pagination] 使用已提取的 xpath 翻页失败: {e}")
        
        # 如果没有预提取的 xpath 或者预提取的失败了，尝试常见选择器
        print(f"[Pagination] 尝试使用常见选择器查找...")
        
        # 常见的下一页按钮选择器（按优先级排列）
        next_page_selectors = [
            # 文字类
            "//a[contains(text(), '下一页')]",
            "//button[contains(text(), '下一页')]",
            "//span[contains(text(), '下一页')]",
            "//a[contains(text(), '下页')]",
            "//a[contains(text(), '>>')]",
            "//a[contains(text(), '>')]",
            "//button[contains(text(), '>>')]",
            "//button[contains(text(), '>')]",
            # class 类
            "//*[contains(@class, 'next')]//a",
            "//*[contains(@class, 'next')]//button",
            "//*[contains(@class, 'next')]",
            "//*[contains(@class, 'pagination-next')]",
            "//a[contains(@class, 'next')]",
            "//button[contains(@class, 'next')]",
            "//li[contains(@class, 'next')]/a",
            "//li[contains(@class, 'next')]/button",
            # aria-label 类
            "//*[@aria-label='下一页']",
            "//*[@aria-label='Next']",
            "//*[@aria-label='next']",
            # title 类
            "//a[@title='下一页']",
            "//button[@title='下一页']",
            # icon 类（一些网站用 icon）
            "//a[contains(@class, 'icon-next')]",
            "//i[contains(@class, 'icon-next')]/parent::*",
            # ant-design 等 UI 框架的分页
            "//li[contains(@class, 'ant-pagination-next')]//*[not(@disabled)]",
            "//li[contains(@class, 'el-pagination')]/button[contains(@class, 'btn-next')]",
        ]
        
        # 遍历选择器查找
        for selector in next_page_selectors:
            try:
                locator = self.page.locator(f"xpath={selector}")
                count = await locator.count()
                
                if count > 0:
                    # 找到了匹配的元素
                    element = locator.first
                    
                    # 检查是否可点击（没有 disabled）
                    is_disabled = await element.get_attribute("disabled")
                    class_attr = await element.get_attribute("class") or ""
                    aria_disabled = await element.get_attribute("aria-disabled")
                    
                    if is_disabled or "disabled" in class_attr or aria_disabled == "true":
                        print(f"[Pagination] 找到下一页按钮但已禁用: {selector}")
                        continue
                    
                    # 检查元素是否可见
                    if not await element.is_visible():
                        continue
                    
                    print(f"[Pagination] 找到下一页按钮: {selector}")
                    
                    # 记录当前 URL，用于验证翻页是否成功
                    old_url = self.page.url
                    
                    # 点击下一页
                    await element.click(timeout=5000)
                    await asyncio.sleep(2)  # 等待页面加载
                    
                    # 验证是否翻页成功（URL 变化或页面内容变化）
                    new_url = self.page.url
                    
                    # 缓存成功的 xpath
                    self.pagination_xpath = selector
                    self.current_page_num += 1
                    print(f"[Pagination] ✓ 翻页成功，当前第 {self.current_page_num} 页")
                    return True
                    
            except Exception as e:
                # 这个选择器不行，继续尝试下一个
                continue
        
        print(f"[Pagination] ✗ 未找到下一页按钮，可能已到最后一页")
        return False
    
    async def _find_next_page_with_llm(self, screenshot_base64: str) -> bool:
        """
        使用 LLM 视觉识别并点击下一页按钮
        
        Returns:
            是否成功翻页
        """
        print(f"[Pagination-LLM] 使用 LLM 视觉识别下一页按钮...")
        
        system_prompt = """你是一个网页爬虫专家。请帮我找到页面上的"下一页"分页按钮。

观察截图，找到分页区域的"下一页"按钮或箭头（>、>>、Next 等）。

返回格式（严格 JSON）：
{"found": true, "mark_id": 123, "reasoning": "在页面底部找到了下一页按钮"}
或
{"found": false, "reasoning": "页面没有分页按钮或已到最后一页"}

注意：
- 只返回"下一页"按钮，不要返回页码数字
- 如果按钮呈灰色/禁用状态，说明已到最后一页，返回 found: false
- 不要返回 markdown 代码块，只返回纯 JSON"""
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=[
                {"type": "text", "text": f"当前在第 {self.current_page_num} 页，请找到下一页按钮"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_base64}"}},
            ]),
        ]
        
        try:
            response = await self.decider.llm.ainvoke(messages)
            response_text = response.content
            
            # 解析 JSON
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                data = json.loads(json_match.group())
                
                if data.get("found") and data.get("mark_id"):
                    mark_id = data["mark_id"]
                    print(f"[Pagination-LLM] 找到下一页按钮 [{mark_id}]: {data.get('reasoning', '')}")
                    
                    # 点击元素
                    locator = self.page.locator(f'[data-som-id="{mark_id}"]')
                    if await locator.count() > 0:
                        await locator.first.click(timeout=5000)
                        await asyncio.sleep(2)
                        self.current_page_num += 1
                        print(f"[Pagination-LLM] ✓ 翻页成功，当前第 {self.current_page_num} 页")
                        return True
                else:
                    print(f"[Pagination-LLM] 未找到下一页: {data.get('reasoning', '')}")
        except Exception as e:
            print(f"[Pagination-LLM] LLM 识别失败: {e}")
        
        return False
    
    async def _replay_nav_steps(self) -> None:
        """重放导航步骤（使用记录的 xpath）"""
        for step in self.nav_steps:
            if not step.get("success"):
                continue
            
            action_type = step.get("action")
            if action_type not in ["click", "CLICK"]:
                continue
            
            # 获取 xpath（优先使用 priority 最小的）
            xpath_candidates = step.get("clicked_element_xpath_candidates", [])
            if not xpath_candidates:
                continue
            
            # 按 priority 排序，取第一个
            xpath_candidates_sorted = sorted(xpath_candidates, key=lambda x: x.get("priority", 99))
            xpath = xpath_candidates_sorted[0].get("xpath") if xpath_candidates_sorted else None
            
            if not xpath:
                continue
            
            target_text = step.get("target_text") or step.get("clicked_element_text", "")
            print(f"[Replay] 点击: {target_text[:30]}... (xpath: {xpath[:50]}...)")
            
            try:
                locator = self.page.locator(f"xpath={xpath}")
                if await locator.count() > 0:
                    await locator.first.click(timeout=5000)
                    await asyncio.sleep(1)
                    print(f"[Replay] ✓ 点击成功")
                else:
                    print(f"[Replay] ⚠ 元素未找到，跳过")
            except Exception as e:
                print(f"[Replay] ✗ 点击失败: {e}")
    
    async def _collect_phase_with_llm(self) -> None:
        """收集阶段：让 LLM 遍历列表页收集所有 URL，支持多页翻页"""
        # 确保回到列表页开始位置
        print(f"[Collect] 返回列表页开始位置...")
        await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1)
        
        max_scrolls = config.url_collector.max_scrolls
        no_new_threshold = config.url_collector.no_new_url_threshold
        target_url_count = config.url_collector.target_url_count  # 目标 URL 数量
        max_pages = config.url_collector.max_pages  # 最大翻页次数
        
        print(f"[Collect] 目标：收集 {target_url_count} 个 URL（当前已有 {len(self.collected_urls)} 个）")
        print(f"[Collect] 最大翻页次数: {max_pages}")
        
        # 重置分页状态
        self.current_page_num = 1
        
        # 外层循环：翻页
        while self.current_page_num <= max_pages:
            print(f"\n[Collect] ===== 第 {self.current_page_num} 页 =====")
            
            # 检查是否达到目标
            if len(self.collected_urls) >= target_url_count:
                print(f"[Collect] ✓ 已达到目标数量 {target_url_count}，结束收集")
                break
            
            scroll_count = 0
            last_url_count = len(self.collected_urls)
            no_new_urls_count = 0
            
            # 内层循环：当前页滚动收集
            while scroll_count < max_scrolls and no_new_urls_count < no_new_threshold:
                # 检查是否达到目标
                if len(self.collected_urls) >= target_url_count:
                    print(f"[Collect] ✓ 已达到目标数量 {target_url_count}，结束收集")
                    break
                
                print(f"\n[Collect] ----- 第 {self.current_page_num} 页，滚动 {scroll_count + 1}/{max_scrolls} -----")
                
                # 扫描页面
                await clear_overlay(self.page)
                snapshot = await inject_and_scan(self.page)
                screenshot_bytes, screenshot_base64 = await capture_screenshot_with_marks(self.page)
                
                # 让 LLM 识别当前视图的详情链接
                llm_decision = await self._ask_llm_for_decision(snapshot, screenshot_base64)
                
                if llm_decision and llm_decision.get("action") == "select_detail_links":
                    mark_ids = llm_decision.get("mark_ids", [])
                    print(f"[Collect] LLM 识别到 {len(mark_ids)} 个详情链接")
                    
                    # 获取URL 候选
                    candidates = [m for m in snapshot.marks if m.mark_id in mark_ids]
                    
                    # 提取 URL（如果连续失败，提前退出）
                    consecutive_failures = 0
                    for candidate in candidates:
                        url = await self._extract_url_from_element(candidate, snapshot)
                        if url and url not in self.collected_urls:
                            self.collected_urls.append(url)
                            consecutive_failures = 0  # 重置失败计数
                        else:
                            consecutive_failures += 1
                            if consecutive_failures >= 3:
                                print(f"[Collect] 连续 {consecutive_failures} 个元素无法获取 URL，跳过剩余元素")
                                break
                
                # 检查是否有新 URL
                current_count = len(self.collected_urls)
                if current_count == last_url_count:
                    no_new_urls_count += 1
                    print(f"[Collect] 连续 {no_new_urls_count} 次无新 URL")
                else:
                    no_new_urls_count = 0
                    print(f"[Collect] ✓ 当前已收集 {current_count} 个 URL（新增 {current_count - last_url_count} 个）")
                    last_url_count = current_count
                
                # 滚动页面
                await self.page.evaluate("window.scrollBy(0, 500)")
                await asyncio.sleep(0.5)
                scroll_count += 1
            
            # 当前页收集完成，尝试翻页
            if len(self.collected_urls) >= target_url_count:
                break
            
            # 尝试翻页
            page_turned = await self._find_and_click_next_page()
            if not page_turned:
                # 如果常规方法找不到，尝试用 LLM
                await clear_overlay(self.page)
                snapshot = await inject_and_scan(self.page)
                screenshot_bytes, screenshot_base64 = await capture_screenshot_with_marks(self.page)
                page_turned = await self._find_next_page_with_llm(screenshot_base64)
            
            if not page_turned:
                print(f"[Collect] 无法翻页，结束收集")
                break
        
        print(f"\n[Collect] 收集完成!")
        print(f"  - 共翻页 {self.current_page_num} 页")
        print(f"  - 收集到 {len(self.collected_urls)} 个 URL")
    
    async def _save_result(self, result: URLCollectorResult, crawler_script: str = "") -> None:
        """保存结果到文件"""
        output_file = self.output_dir / "collected_urls.json"
        
        # 转换为可序列化的格式
        data = {
            "list_page_url": result.list_page_url,
            "task_description": result.task_description,
            "collected_urls": result.collected_urls,
            "nav_steps": self.nav_steps,  # 添加导航步骤记录
            "detail_visits": [
                {
                    "list_page_url": v.list_page_url,
                    "detail_page_url": v.detail_page_url,
                    "clicked_element_tag": v.clicked_element_tag,
                    "clicked_element_text": v.clicked_element_text,
                    "clicked_element_href": v.clicked_element_href,
                    "clicked_element_role": v.clicked_element_role,
                    "clicked_element_xpath_candidates": v.clicked_element_xpath_candidates,
                }
                for v in result.detail_visits
            ],
            "common_pattern": {
                "tag_pattern": result.common_pattern.tag_pattern if result.common_pattern else None,
                "role_pattern": result.common_pattern.role_pattern if result.common_pattern else None,
                "text_pattern": result.common_pattern.text_pattern if result.common_pattern else None,
                "href_pattern": result.common_pattern.href_pattern if result.common_pattern else None,
                "xpath_pattern": result.common_pattern.xpath_pattern if result.common_pattern else None,
                "confidence": result.common_pattern.confidence if result.common_pattern else 0,
            } if result.common_pattern else None,
            "created_at": result.created_at,
        }
        
        output_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[Save] 结果已保存到: {output_file}")
        
        # 也保存一个纯 URL 列表
        urls_file = self.output_dir / "urls.txt"
        urls_file.write_text("\n".join(result.collected_urls), encoding="utf-8")
        print(f"[Save] URL 列表已保存到: {urls_file}")
        
        # 保存生成的爬虫脚本
        if crawler_script:
            script_file = self.output_dir / "spider.py"
            script_file.write_text(crawler_script, encoding="utf-8")
            print(f"[Save] Scrapy 爬虫脚本已保存到: {script_file}")
            print(f"[Save] 运行方式: scrapy runspider {script_file} -o output.json")
            print(f"[Save] 或者: python {script_file}")  # 如果脚本包含 __main__ 入口


# ============================================================================
# 便捷函数
# ============================================================================


async def collect_detail_urls(
    page: "Page",
    list_url: str,
    task_description: str,
    explore_count: int = 3,
    output_dir: str = "output",
) -> URLCollectorResult:
    """收集详情页 URL 的便捷函数"""
    collector = URLCollector(
        page=page,
        list_url=list_url,
        task_description=task_description,
        explore_count=explore_count,
        output_dir=output_dir,
    )
    return await collector.run()
