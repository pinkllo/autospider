# batch_collector.py - 批量爬取器

batch_collector.py 模块提供基于配置文件执行批量 URL 收集的功能，支持断点续爬。

---

## 📁 文件路径

```
src/autospider/crawler/batch_collector.py
```

---

## 📑 函数目录

### 🚀 核心类
- `BatchCollector` - 批量爬取器主类

### 🔧 主要方法
- `run()` - 运行收集流程
- `collect_from_config()` - 从配置文件执行批量收集
- `_load_config()` - 加载配置文件
- `_initialize_handlers()` - 初始化各个处理器

### 🔍 内部方法
- `_preload_config()` - 预加载配置文件
- `_resume_to_target_page()` - 使用三阶段策略恢复到目标页
- `_save_progress()` - 保存收集进度
- `_create_result()` - 创建收集结果
- `_create_empty_result()` - 创建空结果

---

## 🚀 核心功能

### BatchCollector

批量爬取器，继承自 BaseCollector，基于配置文件执行批量 URL 收集。

```python
from autospider.crawler.batch_collector import BatchCollector

# 创建批量爬取器
collector = BatchCollector(
    page=page,
    config_path="output/collection_config.json",
    output_dir="output"
)

# 运行收集流程
result = await collector.run()

print(f"收集到 {len(result.collected_urls)} 个 URL")
```

### 收集流程

BatchCollector 实现基于配置文件的收集流程：

**Phase 0: 加载配置**
```python
# 加载配置文件
collection_config = CollectionConfig.from_dict(data)

# 提取配置信息
list_url = collection_config.list_url
task_description = collection_config.task_description
nav_steps = collection_config.nav_steps
common_detail_xpath = collection_config.common_detail_xpath
```

**Phase 1: 导航到列表页**
```python
# 导航到列表页
await page.goto(list_url, wait_until="domcontentloaded", timeout=30000)
```

**Phase 2: 重放导航步骤**
```python
# 重放已保存的导航步骤
nav_success = await navigation_handler.replay_nav_steps(nav_steps)
```

**Phase 3: 断点恢复**
```python
# 跳转到目标页
actual_page = await collector._resume_to_target_page(target_page_num)
```

**Phase 4: 收集阶段**
```python
# 使用公共 xpath 遍历列表页
await collector._collect_phase_with_xpath()

# 或使用 LLM 遍历
await collector._collect_phase_with_llm()
```

---

## 💡 特性说明

### 配置文件驱动

BatchCollector 从配置文件读取所有必要信息：

```python
# 配置文件结构
{
    "list_url": "https://example.com/list",
    "task_description": "收集商品详情页链接",
    "nav_steps": [...],
    "common_detail_xpath": "//a[@class='product-link']",
    "pagination_xpath": "//a[contains(text(),'下一页')]",
    "jump_widget_xpath": {
        "input": "//input[@class='page-input']",
        "button": "//button[@class='jump-btn']"
    }
}
```

### 断点续爬

支持从上次中断的位置继续收集：

```python
# 加载历史进度
previous_progress = progress_persistence.load_progress()

# 恢复速率控制器状态
rate_controller.current_level = previous_progress.backoff_level
rate_controller.consecutive_success_count = previous_progress.consecutive_success_pages

# 跳转到目标页
actual_page = await collector._resume_to_target_page(target_page_num)
```

### 两种收集模式

1. **XPath 模式**：使用公共 XPath 直接提取 URL（快速、稳定）
2. **LLM 模式**：使用 LLM 识别详情页链接（灵活、智能）

```python
if common_detail_xpath:
    # XPath 模式
    await collector._collect_phase_with_xpath()
else:
    # LLM 模式
    await collector._collect_phase_with_llm()
```

### 配置持久化

自动保存配置和进度：

```python
# 保存配置
collection_config = CollectionConfig(
    nav_steps=nav_steps,
    common_detail_xpath=common_detail_xpath,
    pagination_xpath=pagination_xpath,
    jump_widget_xpath=jump_widget_xpath,
    list_url=list_url,
    task_description=task_description,
)
config_persistence.save(collection_config)

# 保存进度
progress = CollectionProgress(
    status="RUNNING",
    list_url=list_url,
    task_description=task_description,
    current_page_num=current_page_num,
    collected_count=len(collected_urls),
    backoff_level=rate_controller.current_level,
    consecutive_success_pages=rate_controller.consecutive_success_count,
)
progress_persistence.save_progress(progress)
```

---

## 🔧 使用示例

### 完整的批量收集流程

```python
import asyncio
from playwright.async_api import async_playwright
from autospider.crawler.batch_collector import BatchCollector

async def batch_collect():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # 创建批量爬取器
        collector = BatchCollector(
            page=page,
            config_path="output/collection_config.json",
            output_dir="output"
        )

        # 运行收集流程
        result = await collector.run()

        print(f"收集到 {len(result.collected_urls)} 个 URL")

        await browser.close()

# 运行
asyncio.run(batch_collect())
```

### 使用便捷函数

```python
from autospider.crawler.batch_collector import batch_collect_urls

# 使用便捷函数
result = await batch_collect_urls(
    page=page,
    config_path="output/collection_config.json",
    output_dir="output"
)

print(f"收集到 {len(result.collected_urls)} 个 URL")
```

### 断点续爬

```python
# 收集器会自动检测并恢复之前的进度
collector = BatchCollector(
    page=page,
    config_path="output/collection_config.json",
    output_dir="output"
)

# 如果之前中断过，会自动从断点继续
result = await collector.run()
```

### 自定义输出目录

```python
# 指定不同的输出目录
collector = BatchCollector(
    page=page,
    config_path="configs/my_config.json",
    output_dir="output/my_collection"
)

result = await collector.run()
```

---

## 📝 最佳实践

### 配置文件管理

1. **版本控制**：将配置文件纳入版本控制
2. **命名规范**：使用有意义的配置文件名
3. **文档说明**：为配置文件添加注释说明

### 断点续爬

1. **定期保存**：每页收集后保存进度
2. **验证配置**：确保历史配置与当前任务匹配
3. **恢复状态**：恢复速率控制器等状态

### 收集模式选择

1. **优先 XPath**：如果已提取公共 XPath，优先使用 XPath 模式
2. **LLM 备用**：如果 XPath 不可用，使用 LLM 模式
3. **性能考虑**：XPath 模式比 LLM 模式更快速、更稳定

### 错误处理

1. **捕获异常**：妥善处理各种异常情况
2. **应用惩罚**：遭遇反爬时应用速率惩罚
3. **记录日志**：详细记录操作日志便于调试

---

## 🔍 故障排除

### 常见问题

1. **配置文件加载失败**
   - 检查配置文件路径是否正确
   - 验证配置文件格式是否正确
   - 确认配置文件是否存在

2. **导航步骤重放失败**
   - 检查导航步骤是否正确
   - 验证页面结构是否发生变化
   - 确认元素选择器是否有效

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
# 检查配置加载
print(f"列表页: {collector.list_url}")
print(f"任务描述: {collector.task_description}")
print(f"导航步骤: {len(collector.nav_steps)}")
print(f"公共 XPath: {collector.common_detail_xpath}")

# 检查收集进度
print(f"当前页: {pagination_handler.current_page_num}")
print(f"已收集: {len(collector.collected_urls)}")
print(f"降速等级: {rate_controller.current_level}")

# 检查配置文件
import json
config_data = json.loads(Path("output/collection_config.json").read_text())
print(json.dumps(config_data, indent=2))
```

---

## 📚 方法参考

### BatchCollector 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `run()` | 无 | URLCollectorResult | 运行收集流程 |
| `collect_from_config()` | 无 | URLCollectorResult | 从配置文件执行批量收集 |
| `_load_config()` | 无 | bool | 加载配置文件 |
| `_initialize_handlers()` | 无 | None | 初始化各个处理器 |
| `_preload_config()` | 无 | None | 预加载配置文件 |
| `_resume_to_target_page()` | target_page_num, jump_widget_xpath, pagination_xpath | int | 使用三阶段策略恢复到目标页 |
| `_save_progress()` | 无 | None | 保存收集进度 |
| `_create_result()` | 无 | URLCollectorResult | 创建收集结果 |
| `_create_empty_result()` | 无 | URLCollectorResult | 创建空结果 |

### 便捷函数

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `batch_collect_urls()` | page, config_path, output_dir | URLCollectorResult | 批量收集 URL 的便捷函数 |

---

## 📄 配置文件格式

### collection_config.json

```json
{
    "list_url": "https://example.com/list",
    "task_description": "收集商品详情页链接",
    "nav_steps": [
        {
            "action": "click",
            "mark_id": 5,
            "target_text": "筛选按钮"
        }
    ],
    "common_detail_xpath": "//a[@class='product-link']",
    "pagination_xpath": "//a[contains(text(),'下一页')]",
    "jump_widget_xpath": {
        "input": "//input[@class='page-input']",
        "button": "//button[@class='jump-btn']"
    }
}
```

### 配置字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `list_url` | string | 是 | 列表页 URL |
| `task_description` | string | 是 | 任务描述 |
| `nav_steps` | array | 否 | 导航步骤列表 |
| `common_detail_xpath` | string | 否 | 公共详情页 XPath |
| `pagination_xpath` | string | 否 | 分页控件 XPath |
| `jump_widget_xpath` | object | 否 | 跳转控件 XPath |

---

*最后更新: 2026-01-08*
