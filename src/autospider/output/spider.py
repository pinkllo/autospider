#!/usr/bin/env python
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

任务描述：访问提供的 URL，识别列表页中的项目条目，提取前 10 个项目的详情链接或直接提取页面上的'统一交易标识码'字段。若标识码仅在详情页，则进入详情页提取；若在列表页直接可见，则直接采集。
列表页 URL：https://ygp.gdzwfw.gov.cn/#/44/jygg
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright


# ============================================================================
# 配置
# ============================================================================

CONFIG = {
    "urls_file": "output/urls.txt",   # URL 列表文件（已由 url_collector 生成）
    "output_dir": "output",           # 输出目录
    "headless": True,                 # 是否无头模式
    "timeout": 30000,                 # 页面加载超时（毫秒）
}


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
        logger.info(f"\n[Crawler] 开始爬取 {len(urls)} 个详情页...")
        
        for i, url in enumerate(urls, 1):
            logger.info(f"[Crawler] ({i}/{len(urls)}) {url[:100]}...")
            
            try:
                data = await self._crawl_one(url)
                if data:
                    self.results.append(data)
                    logger.info(f"[Crawler] ✓ 成功: {data.get('title', '')[:50]}")
            except Exception as e:
                logger.info(f"[Crawler] ✗ 爬取失败: {e}")
        
        # 保存结果
        self._save_results()
        
        logger.info(f"\n[Crawler] 爬取完成! 成功 {len(self.results)}/{len(urls)} 个")
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
            
            return {
                "url": url,
                "title": title,
                "content": content,
                "crawled_at": datetime.now().isoformat(),
            }
            
        except Exception as e:
            logger.info(f"[Crawler] 页面加载失败: {e}")
            return None
    
    def _save_results(self):
        """保存结果"""
        output_file = self.output_dir / "results.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        logger.info(f"[Crawler] 结果已保存到: {output_file}")


# ============================================================================
# 主函数
# ============================================================================

def load_urls() -> list[str]:
    """从文件加载 URL 列表"""
    urls_file = Path(CONFIG["urls_file"])
    
    if not urls_file.exists():
        logger.info(f"[Error] URL 文件不存在: {urls_file}")
        logger.info(f"[Error] 请先运行 url_collector 收集 URL")
        return []
    
    urls = urls_file.read_text(encoding="utf-8").strip().split("\n")
    urls = [u.strip() for u in urls if u.strip()]
    
    logger.info(f"[Main] 从 {urls_file} 加载了 {len(urls)} 个 URL")
    return urls


async def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("详情页爬虫脚本")
    logger.info("=" * 60)
    
    # 1. 加载已收集的 URL 列表
    urls = load_urls()
    if not urls:
        logger.info("[Main] 没有 URL 可爬取，退出")
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
    
    logger.info("\n" + "=" * 60)
    logger.info("爬取完成!")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
