from __future__ import annotations


def build_detail_crawler_script(
    *,
    list_url: str,
    task_description: str,
    nav_xpaths: list[dict],
    detail_xpath: str | None,
) -> str:
    return f'''#!/usr/bin/env python
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
导航 xpath 数量：{len(nav_xpaths)}
详情链接 xpath：{detail_xpath or "N/A"}
"""

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright


CONFIG = {{
    "urls_file": "output/urls.txt",
    "output_dir": "output",
    "headless": True,
    "timeout": 30000,
}}


class DetailCrawler:
    def __init__(self, page, output_dir: str):
        self.page = page
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results = []

    async def crawl(self, urls: list[str]) -> list[dict]:
        print(f"\\\\n[Crawler] 开始爬取 {{len(urls)}} 个详情页...")
        for i, url in enumerate(urls, 1):
            print(f"[Crawler] ({{i}}/{{len(urls)}}) {{url[:100]}}...")
            try:
                data = await self._crawl_one(url)
                if data:
                    self.results.append(data)
                    print(f"[Crawler] ✓ 成功: {{data.get('title', '')[:50]}}")
            except Exception as exc:
                print(f"[Crawler] ✗ 爬取失败: {{exc}}")
        self._save_results()
        print(f"\\\\n[Crawler] 爬取完成! 成功 {{len(self.results)}}/{{len(urls)}} 个")
        return self.results

    async def _crawl_one(self, url: str) -> dict | None:
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=CONFIG["timeout"])
            await asyncio.sleep(1)
            title = await self.page.title()
            content = ""
            try:
                content_element = self.page.locator("article, .content, .detail, main, #content").first
                if await content_element.count() > 0:
                    content = await content_element.inner_text()
                else:
                    content = await self.page.locator("body").inner_text()
                content = content[:5000]
            except Exception:
                pass
            return {{
                "url": url,
                "title": title,
                "content": content,
                "crawled_at": "",
            }}
        except Exception as exc:
            print(f"[Crawler] 页面加载失败: {{exc}}")
            return None

    def _save_results(self) -> None:
        output_file = self.output_dir / "results.json"
        with open(output_file, "w", encoding="utf-8") as handle:
            json.dump(self.results, handle, ensure_ascii=False, indent=2)
        print(f"[Crawler] 结果已保存到: {{output_file}}")


def load_urls() -> list[str]:
    urls_file = Path(CONFIG["urls_file"])
    if not urls_file.exists():
        print(f"[Error] URL 文件不存在: {{urls_file}}")
        print("[Error] 请先运行 url_collector 收集 URL")
        return []
    urls = urls_file.read_text(encoding="utf-8").strip().split("\\\\n")
    urls = [item.strip() for item in urls if item.strip()]
    print(f"[Main] 从 {{urls_file}} 加载了 {{len(urls)}} 个 URL")
    return urls


async def main() -> None:
    print("=" * 60)
    print("详情页爬虫脚本")
    print("=" * 60)
    urls = load_urls()
    if not urls:
        print("[Main] 没有 URL 可爬取，退出")
        return
    output_dir = Path(CONFIG["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=CONFIG["headless"])
        context = await browser.new_context()
        page = await context.new_page()
        try:
            crawler = DetailCrawler(page, CONFIG["output_dir"])
            await crawler.crawl(urls)
        finally:
            await browser.close()
    print("\\\\n" + "=" * 60)
    print("爬取完成!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
'''
