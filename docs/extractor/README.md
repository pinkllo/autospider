# Extractor 模块

Extractor 模块是 AutoSpider 的智能规则发现引擎，通过 LLM 理解页面语义，自动分析和提取关键信息。该模块支持 URL 收集和 XPath 脚本生成，能够将自然语言任务转化为可执行的爬虫脚本。

---

## 模块结构

```
extractor/
├── __init__.py          # 模块入口，导出 ConfigGenerator 和 RuleGenerator
├── config_generator.py  # 配置生成器，生成爬虫配置和脚本
└── collector/           # URL 收集器
    ├── __init__.py      # 收集器模块导出
    └── url_collector.py # URL 收集器实现
```

---

## 📑 函数目录

### 🎯 配置生成器 (config_generator.py)
- `ConfigGenerator` - 配置生成器主类
- `generate()` - 生成配置和脚本
- `_collect_urls()` - 收集详情页 URL
- `_generate_xpath_script()` - 生成 XPath 脚本
- `_generate_config()` - 生成配置文件

### 🔍 URL 收集器 (url_collector.py)
- `URLCollector` - URL 收集器主类
- `run()` - 执行 URL 收集任务
- `explore()` - 探索阶段，访问详情页样本
- `collect()` - 收集阶段，批量收集 URL
- `analyze()` - 分析阶段，提取公共 XPath 模式

---

## 🚀 核心功能

### ConfigGenerator

ConfigGenerator 是配置生成器的核心类，负责将自然语言任务转化为可执行的爬虫配置和脚本。

```python
from autospider import ConfigGenerator

generator = ConfigGenerator()

result = await generator.generate(
    list_url="https://example.com/products",
    task_description="采集商品信息，包括商品名称、价格、库存状态",
    max_pages=10
)

print(f"生成的配置: {result.config}")
print(f"生成的脚本: {result.script}")
```

### URLCollector

URLCollector 是 URL 收集器的核心类，负责从列表页收集详情页 URL。

```python
from autospider import URLCollector

collector = URLCollector(
    list_url="https://example.com/products",
    task_description="采集商品详情页",
    explore_count=5,
    common_detail_xpath=None,
    redis_manager=None
)

result = await collector.run()
print(f"收集到 {len(result.detail_urls)} 个详情页 URL")
```

---

## 💡 特性说明

### 智能规则发现

通过 LLM 理解页面语义，自动发现数据提取规则：

```python
# 自动识别商品信息字段
fields = {
    "商品名称": "h1.product-title",
    "价格": "span.price",
    "库存": "div.stock-status",
    "描述": "div.description"
}

# 生成稳定的 XPath 选择器
xpath_script = generator._generate_xpath_script(fields)
```

### 多阶段探索

URLCollector 采用三阶段探索策略：

1. **探索阶段**：访问详情页样本，了解页面结构
2. **收集阶段**：批量收集详情页 URL
3. **分析阶段**：提取公共 XPath 模式

### 断点续传

支持从检查点恢复 URL 收集任务：

```python
# 保存收集进度
await collector.save_progress(current_page, collected_urls)

# 恢复收集进度
current_page, collected_urls = await collector.load_progress()
```

---

## 🔧 使用示例

### 完整的配置生成流程

```python
import asyncio
from autospider import ConfigGenerator

async def generate_crawler_config():
    """生成爬虫配置和脚本"""

    generator = ConfigGenerator()

    # 生成配置和脚本
    result = await generator.generate(
        list_url="https://example.com/products",
        task_description="采集商品信息，包括商品名称、价格、库存状态和商品描述",
        max_pages=10
    )

    # 保存配置文件
    with open("config.yaml", "w", encoding="utf-8") as f:
        f.write(result.config)

    # 保存脚本文件
    with open("crawler_script.py", "w", encoding="utf-8") as f:
        f.write(result.script)

    print("配置和脚本已生成")
    print(f"配置文件: config.yaml")
    print(f"脚本文件: crawler_script.py")

    return result

# 使用示例
asyncio.run(generate_crawler_config())
```

### URL 收集流程

```python
import asyncio
from autospider import URLCollector

async def collect_product_urls():
    """收集商品详情页 URL"""

    collector = URLCollector(
        list_url="https://example.com/products",
        task_description="采集商品详情页",
        explore_count=5,
        common_detail_xpath=None,
        redis_manager=None
    )

    # 运行收集任务
    result = await collector.run()

    print(f"收集完成!")
    print(f"详情页 URL 数量: {len(result.detail_urls)}")
    print(f"公共 XPath 模式: {result.common_xpath}")

    # 保存 URL 列表
    with open("product_urls.txt", "w", encoding="utf-8") as f:
        for url in result.detail_urls:
            f.write(url + "\n")

    print("URL 列表已保存到 product_urls.txt")

    return result

# 使用示例
asyncio.run(collect_product_urls())
```

---

## 📝 最佳实践

### 任务描述

1. **清晰明确**：使用清晰、具体的任务描述
2. **字段列举**：明确列出需要提取的字段
3. **示例说明**：提供期望的输出格式
4. **约束条件**：说明任何特殊要求或约束

### 配置优化

1. **探索数量**：根据网站复杂度调整 explore_count
2. **最大页数**：合理设置 max_pages 避免过度采集
3. **XPath 优先级**：提供稳定的 XPath 选择器
4. **缓存策略**：利用 Redis 缓存提高效率

### 错误处理

1. **超时设置**：为每个操作设置合理的超时时间
2. **重试机制**：实现失败重试逻辑
3. **日志记录**：详细记录操作日志
4. **异常捕获**：妥善处理各种异常情况

---

## 🔍 故障排除

### 常见问题

1. **配置生成失败**
   - 检查任务描述是否清晰
   - 验证目标 URL 是否可访问
   - 确认 LLM API 配置正确

2. **URL 收集不完整**
   - 增加 explore_count 参数
   - 检查页面加载是否完整
   - 验证 XPath 选择器准确性

3. **脚本执行错误**
   - 检查生成的脚本语法
   - 验证 XPath 选择器有效性
   - 确认页面结构未发生变化

### 调试技巧

```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 检查生成结果
print(f"配置内容: {result.config}")
print(f"脚本内容: {result.script}")

# 验证 URL 列表
for url in result.detail_urls[:10]:
    print(f"URL: {url}")

# 测试 XPath 选择器
test_xpath = "//div[@class='product-item']"
elements = await page.query_selector_all(test_xpath)
print(f"找到 {len(elements)} 个元素")
```

---

*最后更新: 2026-01-08*
