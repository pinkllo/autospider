# config_generator.py - 配置生成器

config_generator.py 模块提供配置生成功能，通过探索网站生成爬取配置文件。

---

## 📁 文件路径

```
src/autospider/extractor/config_generator.py
```

---

## 📑 函数目录

### 🚀 核心类
- `ConfigGenerator` - 配置生成器主类

### 🔧 主要方法
- `generate_config()` - 生成配置文件（主流程）

### 🔍 内部方法
- `_initialize_handlers()` - 初始化各个处理器
- `_explore_phase()` - 探索阶段：进入多个详情页
- `_handle_current_is_detail()` - 处理当前页面就是详情页
- `_handle_select_detail_links()` - 处理选择详情链接
- `_handle_click_to_enter()` - 处理点击进入详情页
- `_validate_mark_ids()` - 验证 mark_id 与文本的匹配
- `_create_empty_config()` - 创建空配置

---

## 🚀 核心功能

### ConfigGenerator

配置生成器，通过探索网站生成爬取配置文件。

```python
from autospider.extractor.config_generator import ConfigGenerator

# 创建配置生成器
generator = ConfigGenerator(
    page=page,
    list_url="https://example.com/list",
    task_description="收集所有商品详情页链接",
    explore_count=3,
    max_nav_steps=10,
    output_dir="output"
)

# 生成配置文件
config = await generator.generate_config()

print(f"导航步骤: {len(config.nav_steps)}")
print(f"公共 XPath: {config.common_detail_xpath}")
print(f"分页控件: {config.pagination_xpath}")
```

### 配置生成流程

ConfigGenerator 实现四阶段配置生成流程：

**Phase 1: 导航到列表页**
```python
# 导航到列表页
await page.goto(list_url, wait_until="domcontentloaded", timeout=30000)
```

**Phase 2: 导航阶段（筛选操作）**
```python
# 让 LLM 根据任务描述进行筛选操作
nav_success = await navigation_handler.run_navigation_phase()
self.nav_steps = navigation_handler.nav_steps
```

**Phase 3: 探索阶段**
```python
# 进入 N 个不同的详情页
await generator._explore_phase()

# 提取公共 xpath
common_xpath = xpath_extractor.extract_common_xpath(detail_visits)
```

**Phase 3.5-3.6: 提取控件**
```python
# 提取分页控件
pagination_xpath = await pagination_handler.extract_pagination_xpath()

# 提取跳转控件
jump_widget_xpath = await pagination_handler.extract_jump_widget_xpath()
```

**Phase 4: 保存配置**
```python
# 创建并保存配置
collection_config = CollectionConfig(
    nav_steps=nav_steps,
    common_detail_xpath=common_detail_xpath,
    pagination_xpath=pagination_xpath,
    jump_widget_xpath=jump_widget_xpath,
    list_url=list_url,
    task_description=task_description,
)
config_persistence.save(collection_config)
```

---

## 💡 特性说明

### LLM 驱动的探索

使用 LLM 决策探索策略，自动识别详情页链接：

```python
# 使用 LLM 决策
llm_decision = await llm_decision_maker.ask_for_decision(snapshot, screenshot_base64)

decision_type = llm_decision.get("action")

# 处理不同类型的决策
if decision_type == "current_is_detail":
    # 当前页面就是详情页
    pass
elif decision_type == "select_detail_links":
    # 选择详情链接
    pass
elif decision_type == "click_to_enter":
    # 点击进入详情页
    pass
```

### mark_id 验证

验证 LLM 返回的 mark_id 与文本是否匹配：

```python
# 验证 mark_id
if config.url_collector.validate_mark_id:
    mark_ids = generator._validate_mark_ids(mark_id_text_map, snapshot, screenshot_base64)
```

### XPath 提取

从探索记录中提取公共 XPath 模式：

```python
# 提取公共 xpath
common_xpath = xpath_extractor.extract_common_xpath(detail_visits)

if common_xpath:
    print(f"✓ 提取到公共 xpath: {common_xpath}")
else:
    print(f"⚠ 未能提取公共 xpath，将使用 LLM 收集")
```

### 控件提取

自动提取分页控件和跳转控件：

```python
# 提取分页控件
pagination_xpath = await pagination_handler.extract_pagination_xpath()

# 提取跳转控件
jump_widget_xpath = await pagination_handler.extract_jump_widget_xpath()
```

---

## 🔧 使用示例

### 基本使用

```python
import asyncio
from playwright.async_api import async_playwright
from autospider.extractor.config_generator import ConfigGenerator

async def generate_config():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # 创建配置生成器
        generator = ConfigGenerator(
            page=page,
            list_url="https://example.com/products",
            task_description="收集所有商品详情页链接",
            explore_count=3,
            output_dir="output"
        )

        # 生成配置文件
        config = await generator.generate_config()

        print(f"导航步骤: {len(config.nav_steps)}")
        print(f"公共 XPath: {config.common_detail_xpath}")
        print(f"分页控件: {config.pagination_xpath}")
        print(f"跳转控件: {config.jump_widget_xpath}")

        await browser.close()

# 运行
asyncio.run(generate_config())
```

### 使用便捷函数

```python
from autospider.extractor.config_generator import generate_collection_config

# 使用便捷函数
config = await generate_collection_config(
    page=page,
    list_url="https://example.com/list",
    task_description="收集文章详情页链接",
    explore_count=5,
    output_dir="output"
)

print(f"配置已生成: {config}")
```

### 自定义探索数量

```python
# 探索更多详情页以获得更准确的模式
generator = ConfigGenerator(
    page=page,
    list_url="https://example.com/list",
    task_description="收集商品链接",
    explore_count=5,  # 探索 5 个详情页
    max_nav_steps=15,  # 最多 15 个导航步骤
    output_dir="output"
)
```

---

## 📝 最佳实践

### 探索阶段

1. **合理设置探索数量**：通常 3-5 个详情页足够提取模式
2. **确保多样性**：探索不同类型的详情页
3. **记录导航步骤**：保存筛选操作以便重放

### 配置生成

1. **验证 XPath**：确保提取的 XPath 准确有效
2. **测试控件**：测试分页控件和跳转控件是否可用
3. **保存配置**：及时保存配置文件

### mark_id 验证

1. **启用验证**：启用 mark_id 验证提高准确性
2. **设置阈值**：设置合理的相似度阈值
3. **处理失败**：妥善处理验证失败的情况

### 错误处理

1. **捕获异常**：妥善处理各种异常情况
2. **提供默认值**：在探索失败时提供默认配置
3. **记录日志**：详细记录生成过程便于调试

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

3. **控件提取失败**
   - 检查分页控件是否存在
   - 验证控件选择器是否正确
   - 确认控件是否可交互

4. **配置保存失败**
   - 检查输出目录是否存在
   - 验证文件权限是否正确
   - 确认磁盘空间是否充足

### 调试技巧

```python
# 检查探索记录
for visit in generator.detail_visits:
    print(f"详情页: {visit.detail_page_url}")
    print(f"点击元素: {visit.clicked_element_text}")
    print(f"XPath 候选: {visit.clicked_element_xpath_candidates}")

# 检查生成的配置
print(f"导航步骤数: {len(config.nav_steps)}")
print(f"公共 XPath: {config.common_detail_xpath}")
print(f"分页控件: {config.pagination_xpath}")
print(f"跳转控件: {config.jump_widget_xpath}")

# 检查截图目录
import os
screenshot_files = os.listdir(generator.screenshots_dir)
print(f"截图文件数: {len(screenshot_files)}")
```

---

## 📚 方法参考

### ConfigGenerator 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `generate_config()` | 无 | CollectionConfig | 生成配置文件（主流程） |
| `_initialize_handlers()` | 无 | None | 初始化各个处理器 |
| `_explore_phase()` | 无 | None | 探索阶段：进入多个详情页 |
| `_handle_current_is_detail()` | explored | bool | 处理当前页面就是详情页 |
| `_handle_select_detail_links()` | llm_decision, snapshot, screenshot_base64, explored | int | 处理选择详情链接 |
| `_handle_click_to_enter()` | llm_decision, snapshot | bool | 处理点击进入详情页 |
| `_validate_mark_ids()` | mark_id_text_map, snapshot, screenshot_base64 | list[int] | 验证 mark_id 与文本的匹配 |
| `_create_empty_config()` | 无 | CollectionConfig | 创建空配置 |

### 便捷函数

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `generate_collection_config()` | page, list_url, task_description, explore_count, output_dir | CollectionConfig | 生成爬取配置的便捷函数 |

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
