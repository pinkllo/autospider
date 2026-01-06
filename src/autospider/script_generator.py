"""爬虫脚本生成器

从探索记录中分析共同模式,生成 Scrapy + scrapy-playwright 爬虫脚本
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse, parse_qs

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from .config import config
from .llm.prompt_template import render_template
from .persistence import ConfigPersistence

if TYPE_CHECKING:
    from typing import Any


# ============================================================================
# Prompt 模板文件路径
# ============================================================================

PROMPT_TEMPLATE_PATH = str(Path(__file__).parent.parent.parent / "prompts" / "script_generator.yaml")


class ScriptGenerator:
    """爬虫脚本生成器"""
    
    def __init__(self, output_dir: str = "output"):
        """初始化 LLM"""
        self.llm = ChatOpenAI(
            api_key=config.llm.planner_api_key or config.llm.api_key,
            base_url=config.llm.planner_api_base or config.llm.api_base,
            model=config.llm.planner_model or config.llm.model,
            temperature=0.1,
            max_tokens=4096,
        )
        # 持久化管理器，用于读取配置
        self.config_persistence = ConfigPersistence(output_dir)
    
    async def generate_scrapy_playwright_script(
        self,
        list_url: str,
        task_description: str,
        detail_visits: list[dict[str, Any]],
        nav_steps: list[dict[str, Any]],
        collected_urls: list[str],
        common_detail_xpath: str | None = None,
    ) -> str:
        """
        生成 Scrapy + scrapy-playwright 爬虫脚本
        
        Args:
            list_url: 列表页 URL
            task_description: 任务描述
            detail_visits: 详情页访问记录列表
            nav_steps: 导航步骤记录
            collected_urls: 收集到的 URL 列表
            common_detail_xpath: 从探索阶段提取的公共 xpath（可直接复用）
            
        Returns:
            生成的爬虫脚本代码
        """
        print(f"[ScriptGenerator] 开始分析探索记录...")
        
        # 尝试从配置文件读取（如果参数为空）
        if (not nav_steps or not common_detail_xpath) and self.config_persistence.exists():
            print(f"[ScriptGenerator] 尝试从配置文件读取缺失的参数...")
            saved_config = self.config_persistence.load()
            if saved_config:
                if not nav_steps:
                    nav_steps = saved_config.nav_steps
                    print(f"[ScriptGenerator] ✓ 从配置读取到 {len(nav_steps)} 个导航步骤")
                if not common_detail_xpath:
                    common_detail_xpath = saved_config.common_detail_xpath
                    print(f"[ScriptGenerator] ✓ 从配置读取到公共 xpath: {common_detail_xpath}")
        
        if not detail_visits:
            print(f"[ScriptGenerator] 没有探索记录，无法生成脚本")
            return ""
        
        # 提取导航步骤的 xpath（可直接复用到脚本）
        nav_xpaths = self._extract_nav_xpaths(nav_steps)
        print(f"[ScriptGenerator] 提取到 {len(nav_xpaths)} 个导航步骤的 xpath")
        
        # 使用传入的公共 xpath 或从 detail_visits 提取
        detail_xpath = common_detail_xpath
        if not detail_xpath:
            detail_xpath = self._extract_detail_xpath(detail_visits)
        print(f"[ScriptGenerator] 详情链接 xpath: {detail_xpath or 'N/A'}")
        
        # 如果有足够的 xpath 信息，直接生成脚本（无需 LLM）
        if nav_xpaths or detail_xpath:
            print(f"[ScriptGenerator] 使用提取的 xpath 直接生成脚本...")
            script = self._generate_script_from_xpaths(
                list_url=list_url,
                task_description=task_description,
                nav_xpaths=nav_xpaths,
                detail_xpath=detail_xpath,
                collected_urls=collected_urls,
            )
            if script:
                print(f"[ScriptGenerator] ✓ 脚本生成完成（{len(script)} 字符）")
                self._validate_script(script)
                return script
        
        # 不使用 LLM 回退，直接返回空字符串
        # 因为简化模板已经足够使用，不需要复杂的 LLM 生成
        print(f"[ScriptGenerator] ⚠ 无法生成脚本（缺少 xpath 信息）")
        return ""
    
    def _extract_nav_xpaths(self, nav_steps: list[dict[str, Any]]) -> list[dict]:
        """
        从导航步骤中提取 xpath 列表（可直接复用到脚本）
        
        Returns:
            [{"xpath": "...", "text": "...", "action": "click"}, ...]
        """
        nav_xpaths = []
        for step in nav_steps:
            if not step.get("success"):
                continue
            
            action_type = step.get("action", "").lower()
            if action_type not in ["click"]:
                continue
            
            xpath_candidates = step.get("clicked_element_xpath_candidates", [])
            if not xpath_candidates:
                continue
            
            # 按 priority 排序，取最优的
            sorted_candidates = sorted(xpath_candidates, key=lambda x: x.get("priority", 99))
            best_xpath = sorted_candidates[0].get("xpath") if sorted_candidates else None
            
            if best_xpath:
                nav_xpaths.append({
                    "xpath": best_xpath,
                    "text": step.get("clicked_element_text") or step.get("target_text", ""),
                    "action": action_type,
                })
        
        return nav_xpaths
    
    def _extract_detail_xpath(self, detail_visits: list[dict[str, Any]]) -> str | None:
        """
        从探索记录中提取详情链接的公共 xpath
        """
        if len(detail_visits) < 2:
            return None
        
        # 收集所有 xpath 候选
        all_xpaths: list[str] = []
        for visit in detail_visits:
            xpath_candidates = visit.get("clicked_element_xpath_candidates", [])
            # 优先取 priority 最小的
            sorted_candidates = sorted(xpath_candidates, key=lambda x: x.get("priority", 99))
            if sorted_candidates:
                all_xpaths.append(sorted_candidates[0].get("xpath", ""))
        
        if not all_xpaths:
            return None
        
        # 移除索引，找公共模式
        normalized_xpaths = []
        for xpath in all_xpaths:
            # 移除位置谓词 [1], [2], etc.
            normalized = re.sub(r'\[\d+\]', '', xpath)
            normalized_xpaths.append(normalized)
        
        unique_patterns = set(normalized_xpaths)
        if len(unique_patterns) == 1:
            return list(unique_patterns)[0]
        
        return None
    
    def _generate_script_from_xpaths(
        self,
        list_url: str,
        task_description: str,
        nav_xpaths: list[dict],
        detail_xpath: str | None,
        collected_urls: list[str],
    ) -> str:
        """
        生成纯 Playwright 详情页爬虫脚本
        
        核心优化：URL 收集已在 url_collector 阶段完成，
        此脚本只负责读取 urls.txt 并爬取详情页内容！
        """
        # 生成完整脚本 - 直接读取已收集的 URL，只做详情页爬取
        script = f'''#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
详情页爬虫脚本

URL 收集已在前一阶段完成并保存到 urls.txt，
此脚本直接读取 URL 列表并爬取详情页内容。

运行命令：
    python spider.py

依赖安装：
    pip install playwright
    playwright install chromium

任务描述：{task_description}
列表页 URL：{list_url}
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright


# ============================================================================
# 配置
# ============================================================================

CONFIG = {{
    "urls_file": "output/urls.txt",   # URL 列表文件（已由 url_collector 生成）
    "output_dir": "output",           # 输出目录
    "headless": True,                 # 是否无头模式
    "timeout": 30000,                 # 页面加载超时（毫秒）
}}


# ============================================================================
# 详情页爬取器
# ============================================================================

class DetailCrawler:
    """详情页爬取器"""
    
    def __init__(self, page, output_dir: str):
        self.page = page
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results = []
    
    async def crawl(self, urls: list[str]) -> list[dict]:
        """爬取所有详情页"""
        print(f"\\n[Crawler] 开始爬取 {{len(urls)}} 个详情页...")
        
        for i, url in enumerate(urls, 1):
            print(f"[Crawler] ({{i}}/{{len(urls)}}) {{url[:100]}}...")
            
            try:
                data = await self._crawl_one(url)
                if data:
                    self.results.append(data)
                    print(f"[Crawler] ✓ 成功: {{data.get('title', '')[:50]}}")
            except Exception as e:
                print(f"[Crawler] ✗ 爬取失败: {{e}}")
        
        # 保存结果
        self._save_results()
        
        print(f"\\n[Crawler] 爬取完成! 成功 {{len(self.results)}}/{{len(urls)}} 个")
        return self.results
    
    async def _crawl_one(self, url: str) -> dict | None:
        """爬取单个详情页"""
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=CONFIG["timeout"])
            await asyncio.sleep(1)
            
            # 提取基本信息
            title = await self.page.title()
            
            # 提取页面正文（可根据实际页面结构调整选择器）
            content = ""
            try:
                # 尝试获取主要内容区域
                content_element = self.page.locator("article, .content, .detail, main, #content").first
                if await content_element.count() > 0:
                    content = await content_element.inner_text()
                else:
                    # 回退：获取 body 文本
                    content = await self.page.locator("body").inner_text()
                content = content[:5000]  # 限制长度
            except:
                pass
            
            return {{
                "url": url,
                "title": title,
                "content": content,
                "crawled_at": datetime.now().isoformat(),
            }}
            
        except Exception as e:
            print(f"[Crawler] 页面加载失败: {{e}}")
            return None
    
    def _save_results(self):
        """保存结果"""
        output_file = self.output_dir / "results.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        print(f"[Crawler] 结果已保存到: {{output_file}}")


# ============================================================================
# 主函数
# ============================================================================

def load_urls() -> list[str]:
    """从文件加载 URL 列表"""
    urls_file = Path(CONFIG["urls_file"])
    
    if not urls_file.exists():
        print(f"[Error] URL 文件不存在: {{urls_file}}")
        print(f"[Error] 请先运行 url_collector 收集 URL")
        return []
    
    urls = urls_file.read_text(encoding="utf-8").strip().split("\\n")
    urls = [u.strip() for u in urls if u.strip()]
    
    print(f"[Main] 从 {{urls_file}} 加载了 {{len(urls)}} 个 URL")
    return urls


async def main():
    """主函数"""
    print("=" * 60)
    print("详情页爬虫脚本")
    print("=" * 60)
    
    # 1. 加载已收集的 URL 列表
    urls = load_urls()
    if not urls:
        print("[Main] 没有 URL 可爬取，退出")
        return
    
    output_dir = Path(CONFIG["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 2. 启动浏览器爬取详情页
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=CONFIG["headless"])
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            crawler = DetailCrawler(page, CONFIG["output_dir"])
            await crawler.crawl(urls)
            
        finally:
            await browser.close()
    
    print("\\n" + "=" * 60)
    print("爬取完成!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
'''
        
        return script
    
    def _prepare_visits_summary(self, detail_visits: list[dict[str, Any]]) -> list[dict]:
        """准备探索记录摘要"""
        visits_summary = []
        for i, visit in enumerate(detail_visits, 1):
            visits_summary.append({
                "序号": i,
                "详情页URL": visit.get("detail_page_url", ""),
                "点击元素标签": visit.get("clicked_element_tag", ""),
                "点击元素文本": visit.get("clicked_element_text", "")[:50],
                "点击元素href": visit.get("clicked_element_href"),
                "点击元素role": visit.get("clicked_element_role"),
                "XPath候选": [
                    {"xpath": c.get("xpath"), "priority": c.get("priority"), "strategy": c.get("strategy")}
                    for c in visit.get("clicked_element_xpath_candidates", [])[:3]
                ]
            })
        return visits_summary
    
    def _prepare_nav_summary(self, nav_steps: list[dict[str, Any]]) -> list[dict]:
        """准备导航步骤摘要"""
        nav_summary = []
        for step in nav_steps:
            if step.get("success"):
                nav_summary.append({
                    "步骤": step.get("step"),
                    "动作": step.get("action"),
                    "目标文本": step.get("target_text", ""),
                    "思考": step.get("thinking", "")[:100]
                })
        return nav_summary
    
    def _analyze_url_patterns(self, urls: list[str]) -> dict:
        """分析 URL 列表，找出共同模式"""
        if not urls:
            return {"error": "没有 URL 可分析"}
        
        analysis = {
            "total_urls": len(urls),
            "base_urls": [],
            "path_patterns": [],
            "query_params": {},
            "common_parts": {},
            "variable_parts": [],
        }
        
        parsed_urls = [urlparse(url) for url in urls]
        
        # 分析域名
        schemes = set(p.scheme for p in parsed_urls)
        netlocs = set(p.netloc for p in parsed_urls)
        analysis["base_urls"] = [f"{s}://{n}" for s in schemes for n in netlocs]
        
        # 分析路径
        paths = [p.path for p in parsed_urls]
        if paths:
            # 找出路径中的共同前缀
            common_prefix = paths[0]
            for path in paths[1:]:
                while not path.startswith(common_prefix) and common_prefix:
                    common_prefix = common_prefix[:-1]
            analysis["common_parts"]["path_prefix"] = common_prefix
            
            # 分析路径结构
            path_segments = [p.split('/') for p in paths]
            if path_segments:
                max_len = max(len(s) for s in path_segments)
                for i in range(max_len):
                    segments_at_i = [s[i] if i < len(s) else None for s in path_segments]
                    unique_segments = set(seg for seg in segments_at_i if seg)
                    if len(unique_segments) == 1:
                        # 固定部分
                        pass
                    elif len(unique_segments) > 1:
                        # 变量部分
                        analysis["variable_parts"].append({
                            "position": i,
                            "samples": list(unique_segments)[:5],
                            "is_numeric": all(s.isdigit() for s in unique_segments if s),
                        })
        
        # 分析查询参数
        for parsed in parsed_urls:
            params = parse_qs(parsed.query)
            for key, values in params.items():
                if key not in analysis["query_params"]:
                    analysis["query_params"][key] = {"samples": [], "is_constant": True}
                analysis["query_params"][key]["samples"].extend(values)
        
        # 检查哪些参数是常量，哪些是变量
        for key, info in analysis["query_params"].items():
            unique_values = set(info["samples"])
            info["unique_count"] = len(unique_values)
            info["is_constant"] = len(unique_values) == 1
            info["samples"] = list(unique_values)[:5]
        
        # 分析 hash/fragment
        fragments = [p.fragment for p in parsed_urls if p.fragment]
        if fragments:
            analysis["fragments"] = {
                "count": len(fragments),
                "samples": list(set(fragments))[:5],
            }
        
        return analysis
    
    
    def _build_system_prompt(self) -> str:
        """构建系统提示词（从模板文件加载）"""
        return render_template(
            PROMPT_TEMPLATE_PATH,
            section="system_prompt",
        )
    
    
    def _build_user_message(
        self,
        list_url: str,
        task_description: str,
        nav_summary: list[dict],
        visits_summary: list[dict],
        url_samples: list[str],
        url_pattern_analysis: dict,
    ) -> str:
        """构建用户消息（从模板文件加载）"""
        return render_template(
            PROMPT_TEMPLATE_PATH,
            section="user_prompt",
            variables={
                "task_description": task_description,
                "list_url": list_url,
                "nav_summary": json.dumps(nav_summary, ensure_ascii=False, indent=2),
                "visits_count": len(visits_summary),
                "visits_summary": json.dumps(visits_summary, ensure_ascii=False, indent=2),
                "urls_count": len(url_samples),
                "url_samples": json.dumps(url_samples, ensure_ascii=False, indent=2),
                "url_pattern_analysis": json.dumps(url_pattern_analysis, ensure_ascii=False, indent=2),
            }
        )
    
    def _validate_script(self, script: str) -> None:
        """验证生成的脚本结构"""
        if "scrapy_playwright" in script and "scrapy.Spider" in script:
            print(f"[ScriptGenerator] ✓ Scrapy + scrapy-playwright 脚本结构验证通过")
        elif "scrapy" in script.lower():
            print(f"[ScriptGenerator] ⚠ 脚本可能缺少 scrapy-playwright 配置")
        else:
            print(f"[ScriptGenerator] ⚠ 脚本可能不是 Scrapy 格式")


# ============================================================================
# 便捷函数
# ============================================================================


async def generate_crawler_script(
    list_url: str,
    task_description: str,
    detail_visits: list[dict[str, Any]],
    nav_steps: list[dict[str, Any]],
    collected_urls: list[str],
    common_detail_xpath: str | None = None,
    output_dir: str = "output",
) -> str:
    """生成爬虫脚本的便捷函数"""
    generator = ScriptGenerator(output_dir)
    return await generator.generate_scrapy_playwright_script(
        list_url=list_url,
        task_description=task_description,
        detail_visits=detail_visits,
        nav_steps=nav_steps,
        collected_urls=collected_urls,
        common_detail_xpath=common_detail_xpath,
    )
