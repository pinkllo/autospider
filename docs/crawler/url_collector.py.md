# url_collector.py - 详情页 URL 收集器

url_collector.py 模块提供详情页 URL 收集功能，通过探索阶段分析页面模式，然后使用公共脚本批量收集 URL。

---

## 📁 文件路径

```
src/autospider/crawler/url_collector.py
```

---

## 📑 函数目录

### 🚀 核心类
- `URLCollector` - 详情页 URL 收集器主类

### 🔧 主要方法
- `run()` - 运行 URL 收集流程
- `_explore_phase()` - 探索阶段：进入多个详情页
- `_collect_phase_with_xpath()` - 收集阶段：使用公共 xpath
- `_collect_phase_with_llm()` - 收集阶段：使用 LLM
- `_generate_crawler_script()` - 生成爬虫脚本

### 🔍 内部方法
- `_handle_current_is_detail()` - 处理当前页面就是详情页
- `_handle_select_detail_links()` - 处理选择详情链接
- `_handle_click_to_enter()` - 处理点击进入详情页
- `_validate_mark_ids()` - 验证 mark_id 与文本的匹配
- `_resume_to_target_page()` - 断点恢复到目标页

---

## 🚀 核心功能

### URLCollector

详情页 URL 收集器主类，继承自 BaseCollector，增加探索阶段功能。

```python
from autospider.crawler.url_collector import URLCollector

# 创建收集器
collector = URLCollector(
    page=page,
    list_url="https://example.com/list",
    task_description="收集所有商品详情页链接",
    explore_count=3,
    max_nav_steps=10,
    output_dir="output"
)

# 运行收集流程
result = await collector.run()

print(f"收集到 {len(result.collected_urls)} 个 URL")
```

### 收集流程

URLCollector 实现三阶段收集流程：

**Phase 1: 导航到列表页**
```python
# 导航到列表页
await page.goto(list_url, wait_until="domcontentloaded", timeout=30000)
```

**Phase 2: 导航阶段（筛选操作）**
```python
# 让 LLM 根据任务描述进行筛选操作
nav_success = await navigation_handler.run_navigation_phase()
```

**Phase 3: 探索阶段**
```python
# 进入 N 个不同的详情页，记录操作步骤
await collector._explore_phase()

# 提取公共 xpath
common_xpath = xpath_extractor.extract_common_xpath(detail_visits)
```

**Phase 4: 收集阶段**
```python
# 使用公共 xpath 遍历列表页
await collector._collect_phase_with_xpath()

# 或使用 LLM 遍历
await collector._collect_phase_with_llm()
```

**Phase 5: 生成爬虫脚本**
```python
# 生成 Scrapy + scrapy-playwright 爬虫脚本
crawler_script = await collector._generate_crawler_script()
```

---

## 💡 特性说明

### 三阶段收集流程

1. **探索阶段**：进入 N 个不同的详情页，记录每次进入的操作步骤
2. **分析阶段**：分析这 N 次操作的共同模式，提取公共脚本
3. **收集阶段**：使用公共脚本遍历列表页，收集所有详情页的 URL

### 断点续爬

支持从上次中断的位置继续收集：

```python
# 自动加载历史进度
previous_progress = progress_persistence.load_progress()

# 恢复速率控制器状态
rate_controller.current_level = previous_progress.backoff_level
rate_controller.consecutive_success_count = previous_progress.consecutive_success_pages

# 跳转到目标页
actual_page = await collector._resume_to_target_page(target_page_num)
```

### mark_id 验证

验证 LLM 返回的 mark_id 与文本是否匹配：

```python
if config.url_collector.validate_mark_id:
    mark_ids = collector._validate_mark_ids(mark_id_text_map, snapshot, screenshot_base64)
```

### 速率控制

自适应速率控制，遭遇反爬时自动降速：

```python
# 应用速率控制延迟
delay = rate_controller.get_delay()
await asyncio.sleep(delay)

# 记录成功
rate_controller.record_success()

# 应用惩罚（遭遇反爬时）
rate_controller.apply_penalty()
```

---

## 🔧 使用示例

### 完整的收集流程

```python
import asyncio
from playwright.async_api import async_playwright
from autospider.crawler.url_collector import URLCollector

async def collect_urls():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # 创建收集器
        collector = URLCollector(
            page=page,
            list_url="https://example.com/products",
            task_description="收集所有商品详情页链接",
            explore_count=3,
            output_dir="output"
        )

        # 运行收集流程
        result = await collector.run()

        print(f"探索了 {len(result.detail_visits)} 个详情页")
        print(f"收集到 {len(result.collected_urls)} 个 URL")

        await browser.close()

# 运行
asyncio.run(collect_urls())
```

### 自定义探索数量

```python
# 探索更多详情页以获得更准确的模式
collector = URLCollector(
    page=page,
    list_url="https://example.com/list",
    task_description="收集文章详情页链接",
    explore_count=5,  # 探索 5 个详情页
    max_nav_steps=15,  # 最多 15 个导航步骤
    output_dir="output"
)
```

### 断点续爬

```python
# 收集器会自动检测并恢复之前的进度
collector = URLCollector(
    page=page,
    list_url="https://example.com/list",
    task_description="收集商品链接",
    output_dir="output"
)

# 如果之前中断过，会自动从断点继续
result = await collector.run()
```

---

## 📝 最佳实践

### 探索阶段

1. **合理设置探索数量**：通常 3-5 个详情页足够提取模式
2. **确保多样性**：探索不同类型的详情页
3. **记录导航步骤**：保存筛选操作以便重放

### 收集阶段

1. **优先使用 XPath**：XPath 收集比 LLM 收集更快速、更稳定
2. **设置合理目标**：根据实际需求设置 target_url_count
3. **控制翻页次数**：设置 max_pages 避免无限翻页

### 断点续爬

1. **定期保存进度**：每页收集后保存进度
2. **验证配置匹配**：确保历史配置与当前任务匹配
3. **恢复速率状态**：恢复速率控制器的降速等级

### 错误处理

1. **捕获异常**：妥善处理各种异常情况
2. **应用惩罚**：遭遇反爬时应用速率惩罚
3. **记录日志**：详细记录操作日志便于调试

---

## 🔍 故障排除

### 常见问题

1. **探索阶段失败**
   - 检查列表页 URL 是否正确
   - 验证任务描述是否清晰
   - 确认页面加载完成

2. **XPath 提取失败**
   - 检查探索的详情页数量是否足够（至少 2 个）
   - 验证详情页 URL 是否有效
   - 确认元素选择器是否正确

3. **收集阶段卡住**
   - 检查分页控件是否正确识别
   - 验证速率控制延迟是否合理
   - 确认目标 URL 数量是否可达成

4. **断点恢复失败**
   - 检查历史配置是否与当前任务匹配
   - 验证进度文件是否存在且有效
   - 确认跳转控件 XPath 是否正确

### 调试技巧

```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 检查探索记录
for visit in collector.detail_visits:
    print(f"详情页: {visit.detail_page_url}")
    print(f"点击元素: {visit.clicked_element_text}")
    print(f"XPath 候选: {visit.clicked_element_xpath_candidates}")

# 检查收集进度
print(f"当前页: {pagination_handler.current_page_num}")
print(f"已收集: {len(collector.collected_urls)}")
print(f"降速等级: {rate_controller.current_level}")
```

---

## 📚 方法参考

### URLCollector 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `run()` | 无 | URLCollectorResult | 运行 URL 收集流程 |
| `_explore_phase()` | 无 | None | 探索阶段：进入多个详情页 |
| `_collect_phase_with_xpath()` | 无 | None | 收集阶段：使用公共 xpath |
| `_collect_phase_with_llm()` | 无 | None | 收集阶段：使用 LLM |
| `_generate_crawler_script()` | 无 | str | 生成爬虫脚本 |
| `_handle_current_is_detail()` | explored: int | bool | 处理当前页面就是详情页 |
| `_handle_select_detail_links()` | llm_decision, snapshot, screenshot_base64, explored | int | 处理选择详情链接 |
| `_handle_click_to_enter()` | llm_decision, snapshot | bool | 处理点击进入详情页 |
| `_validate_mark_ids()` | mark_id_text_map, snapshot, screenshot_base64 | list[int] | 验证 mark_id 与文本的匹配 |
| `_resume_to_target_page()` | target_page_num, jump_widget_xpath, pagination_xpath | int | 断点恢复到目标页 |

### 便捷函数

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `collect_detail_urls()` | page, list_url, task_description, explore_count, output_dir | URLCollectorResult | 收集详情页 URL 的便捷函数 |

---

*最后更新: 2026-01-08*
