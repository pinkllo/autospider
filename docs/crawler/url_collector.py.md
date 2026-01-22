# URL Collector - 详情页 URL 收集器

## 📋 基本信息

### 文件路径
`d:\autospider\src\autospider\crawler\url_collector.py`

### 核心功能
详情页 URL 收集器（协调器），负责从列表页自动探索、分析并收集所有详情页 URL。它通过 LLM 识别页面结构，并自动提取 XPath 以实现大规模、高效率的采集。

### 设计理念
采用三阶段自适应工作流：
1. **探索阶段 (Explore Phase)**：通过 LLM 引导进入 N 个不同的详情页（默认为 3 个），记录每次进入的操作步骤和元素特征。
2. **分析阶段 (Analysis Phase)**：分析这 N 次操作的共同模式，利用 `XPathExtractor` 自动提取稳定的公共 XPath。
3. **收集阶段 (Collect Phase)**：
   - **XPath 模式**：如果提取成功，则使用 XPath 高效遍历列表页并自动翻页。
   - **LLM 模式**：如果 XPath 提取失败，则降级为使用 LLM 逐页决策收集。

## 📁 类与函数目录

### 主类
- `URLCollector` - 详情页 URL 收集器核心协调器，继承自 `BaseCollector`。

### 便捷函数
- `collect_detail_urls` - 快速启动 URL 收集流程的便捷入口。

### 核心方法
- `run` - 顶层控制流，管理从导航到结果保存的完整生命周期。
- `_explore_phase` - 核心探索逻辑，结合 SoM (Set of Marks) 标注和 LLM 决策。
- `_collect_phase_with_xpath` - 高效采集模式。
- `_collect_phase_with_llm` - 鲁棒性兜底采集模式。

## 🎯 核心功能详解

### URLCollector 类

**功能说明**：详情页 URL 收集器协调器，负责编排各组件（Decider, Extractor, Handler）协同工作。

**初始化参数**：
| 参数名 | 类型 | 描述 | 默认值 |
|--------|------|------|--------|
| page | `Page` | Playwright 页面对象 | 必填 |
| list_url | `str` | 初始列表页 URL | 必填 |
| task_description | `str` | 任务描述（如："采集所有商品详情页"） | 必填 |
| explore_count | `int` | 探索阶段要进入的样本页面数量 | 3 |
| max_nav_steps | `int` | 导航阶段（前置筛选操作）允许的最大步数 | 10 |
| output_dir | `str` | 结果、配置及截图的存储目录 | "output" |

**核心工作流 (run 方法)**：
1. **进度恢复**：检查 `output_dir` 下的 `persistence` 信息，支持从上次中断的页码继续。
2. **导航准备**：执行登录、筛选、排序等前置操作。
3. **智能探索**：识别详情页入口，记录 `DetailPageVisit` 对象。
4. **模式提取**：生成公共 XPath，并保存至 `CollectionConfig`。
5. **翻页采集**：调用 `PaginationHandler` 自动处理复杂的分页逻辑。
6. **脚本生成**：调用 `ScriptGenerator` 生成可脱离本系统运行的 Scrapy 脚本。

## 🚀 关键特性

### 1. 文本优先纠正 (Text-First Resolution)
为了解决网页动态加载导致的标注 ID (mark_id) 偏移问题，系统在点击前会对比 LLM 识别的文本与实际页面元素文本，确保点击位置 100% 准确。

### 2. 断点续爬与速率控制
- **状态持久化**：实时保存已收集的 URL 和当前页码。
- **自适应速率**：根据页面响应速度自动调整采集频率，防止触发反爬虫机制。

### 3. 代码生成 (Code Generation)
采集完成后，系统会自动生成一个名为 `spider.py` 的文件。这是一个基于 `scrapy-playwright` 的完整爬虫，开发者可以将其部署到服务器上进行后续的大规模数据抓取。

## 💡 使用示例

```python
import asyncio
from playwright.async_api import async_playwright
from autospider.crawler.url_collector import collect_detail_urls

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        # 只需要提供任务描述，系统会自动识别“下一页”和“详情页链接”
        result = await collect_detail_urls(
            page=page,
            list_url="https://example.com/news",
            task_description="采集所有新闻报道的详情页 URL",
            explore_count=3
        )
        
        print(f"成功收集到 {len(result.collected_urls)} 个 URL")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
```

## 🛠 故障排除

| 现象 | 可能原因 | 对策 |
|------|----------|------|
| 无法提取 XPath | 列表项结构差异巨大 | 增加 `explore_count` 到 5 或更多 |
| 无法点击翻页 | 分页控件是动态生成的 | 检查 `pagination_handler` 日志，优化任务描述 |
| 采集速度慢 | 触发了速率限制 | 检查 `rate_controller` 状态，或更换代理 |

---
**最后更新**: 2026-01-22
**维护者**: AutoSpider Team