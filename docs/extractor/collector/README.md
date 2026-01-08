# Collector 子模块

Collector 子模块实现 URL 收集功能，负责从列表页自动发现并收集详情页 URL。该模块采用多阶段探索策略，能够智能识别详情页链接并提取公共 XPath 模式。

---

## 📁 模块结构

```
src/autospider/extractor/collector/
├── __init__.py              # 模块导出
└── url_collector.py         # URL 收集器实现
```

---

## 📑 函数目录

### 🔍 URL 收集器 (url_collector.py)
- `URLCollector` - URL 收集器主类
- `run()` - 执行 URL 收集任务
- `explore()` - 探索阶段，访问详情页样本
- `collect()` - 收集阶段，批量收集 URL
- `analyze()` - 分析阶段，提取公共 XPath 模式

---

## 🚀 核心功能

### URL 收集器

URLCollector 是 URL 收集的核心类，负责从列表页收集详情页 URL。

```python
from autospider.extractor.collector import URLCollector

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

### 多阶段探索

URLCollector 采用三阶段探索策略：

1. **探索阶段**：访问详情页样本，了解页面结构
2. **收集阶段**：批量收集详情页 URL
3. **分析阶段**：提取公共 XPath 模式

```python
# 执行探索阶段
await collector.explore()

# 执行收集阶段
await collector.collect()

# 执行分析阶段
await collector.analyze()
```

---

## 💡 特性说明

### 智能链接识别

自动识别详情页链接，过滤掉无关链接：

```python
# 识别详情页链接
detail_links = [
    "https://example.com/product/123",
    "https://example.com/product/456",
    "https://example.com/product/789"
]

# 过滤掉无关链接
filtered_links = [
    link for link in all_links
    if "/product/" in link
]
```

### 公共 XPath 提取

自动提取公共 XPath 模式，用于批量采集：

```python
# 提取公共 XPath
common_xpath = await collector.analyze()

print(f"公共 XPath: {common_xpath}")
```

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

### 完整的 URL 收集流程

```python
import asyncio
from autospider.extractor.collector import URLCollector

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

### 自定义探索策略

```python
import asyncio
from autospider.extractor.collector import URLCollector

async def custom_collect():
    """自定义探索策略"""

    collector = URLCollector(
        list_url="https://example.com/products",
        task_description="采集商品详情页",
        explore_count=10,  # 增加探索数量
        common_detail_xpath="//a[@class='product-link']",  # 提供公共 XPath
        redis_manager=None
    )

    # 分阶段执行
    await collector.explore()
    print(f"探索完成，发现 {len(collector.detail_urls)} 个详情页")

    await collector.collect()
    print(f"收集完成，共 {len(collector.detail_urls)} 个详情页")

    await collector.analyze()
    print(f"分析完成，公共 XPath: {collector.common_xpath}")

    return collector

# 使用示例
asyncio.run(custom_collect())
```

---

## 📝 最佳实践

### 探索策略

1. **探索数量**：根据网站复杂度调整 explore_count
2. **公共 XPath**：提供稳定的公共 XPath 提高准确性
3. **过滤规则**：使用过滤规则排除无关链接
4. **去重机制**：确保 URL 唯一性

### 性能优化

1. **批量处理**：使用批量操作提高效率
2. **并发控制**：合理控制并发请求数量
3. **缓存策略**：利用缓存减少重复请求
4. **延迟控制**：设置合理的请求延迟

### 错误处理

1. **超时设置**：为每个操作设置合理的超时时间
2. **重试机制**：实现失败重试逻辑
3. **日志记录**：详细记录操作日志
4. **异常捕获**：妥善处理各种异常情况

---

## 🔍 故障排除

### 常见问题

1. **URL 收集不完整**
   - 增加 explore_count 参数
   - 检查页面加载是否完整
   - 验证公共 XPath 准确性

2. **公共 XPath 提取失败**
   - 检查页面结构是否一致
   - 验证详情页链接格式
   - 调整分析算法参数

3. **断点续传失败**
   - 检查存储后端是否正常
   - 验证进度数据完整性
   - 确认恢复逻辑正确性

### 调试技巧

```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 检查收集结果
print(f"详情页 URL 数量: {len(result.detail_urls)}")
for url in result.detail_urls[:10]:
    print(f"URL: {url}")

# 检查公共 XPath
print(f"公共 XPath: {result.common_xpath}")

# 测试 XPath 选择器
test_xpath = result.common_xpath
elements = await page.query_selector_all(test_xpath)
print(f"找到 {len(elements)} 个元素")
```

---

*最后更新: 2026-01-08*
