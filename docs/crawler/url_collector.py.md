# URL Collector - 详情页 URL 收集器

## 📋 基本信息

### 文件路径
`d:\autospider\src\autospider\crawler\url_collector.py`

### 核心功能
详情页 URL 收集器（协调器），负责从列表页自动探索、分析并收集所有详情页 URL。

### 设计理念
采用三阶段工作流：
1. **探索阶段**：进入 N 个不同的详情页，记录每次进入的操作步骤
2. **分析阶段**：分析这 N 次操作的共同模式，提取公共 XPath
3. **收集阶段**：使用公共 XPath 遍历列表页，收集所有详情页 URL

## 📁 函数目录

### 主类
- `URLCollector` - 详情页 URL 收集器协调器

### 便捷函数
- `collect_detail_urls` - 收集详情页 URL 的便捷函数

### 核心方法
- `run` - 运行 URL 收集流程
- `_explore_phase` - 探索阶段：进入多个详情页
- `_collect_phase_with_xpath` - 使用公共 XPath 收集 URL
- `_collect_phase_with_llm` - 使用 LLM 遍历列表页收集 URL

## 🎯 核心功能详解

### URLCollector 类

**功能说明**：详情页 URL 收集器协调器，继承自 `BaseCollector`，增加了探索阶段功能。

**初始化参数**：
| 参数名 | 类型 | 描述 | 默认值 |
|--------|------|------|--------|
| page | `Page` | Playwright 页面对象 | 必填 |
| list_url | `str` | 列表页 URL | 必填 |
| task_description | `str` | 任务描述 | 必填 |
| explore_count | `int` | 探索的详情页数量 | 3 |
| max_nav_steps | `int` | 最大导航步骤数 | 10 |
| output_dir | `str` | 输出目录 | "output" |

**核心方法**：

#### run()
**功能**：运行完整的 URL 收集流程，包括导航、探索、提取、收集和生成脚本。

**返回值**：`URLCollectorResult` - 收集结果对象

**执行流程**：
1. 加载历史进度和配置信息
2. 导航到列表页
3. 执行导航阶段（筛选操作）
4. 执行探索阶段（进入详情页）
5. 提取公共 XPath
6. 执行收集阶段（遍历列表页）
7. 持久化配置
8. 生成爬虫脚本
9. 保存结果

#### _explore_phase()
**功能**：探索阶段，进入多个详情页并记录操作步骤。

**执行流程**：
1. 扫描页面并获取 SoM 快照
2. 调用 LLM 决策下一步操作
3. 处理 LLM 决策（点击进入详情页、选择详情链接等）
4. 记录详情页访问信息
5. 返回列表页继续探索

#### _collect_phase_with_xpath()
**功能**：使用公共 XPath 遍历列表页，高效收集所有详情页 URL。

#### _collect_phase_with_llm()
**功能**：当无法提取公共 XPath 时，使用 LLM 遍历列表页收集 URL。

### collect_detail_urls() 便捷函数

**功能**：创建并运行 URLCollector 的便捷函数。

**参数**：同 URLCollector 初始化参数

**返回值**：`URLCollectorResult` - 收集结果对象

## 🚀 特性说明

### 智能探索机制
- 自动进入多个详情页，记录操作步骤
- 支持多种进入详情页的方式（直接点击、选择链接等）
- 自动处理页面滚动和加载

### 断点续传功能
- 支持从上次中断的页码继续收集
- 自动恢复速率控制器状态
- 支持 Redis 持久化存储

### 自适应收集策略
- 优先使用提取的公共 XPath 进行高效收集
- 当 XPath 提取失败时，自动降级为 LLM 遍历
- 支持多种分页控件处理（数字页码、下一页按钮等）

### 脚本自动生成
- 基于收集的 URL 和探索结果，自动生成可独立运行的爬虫脚本
- 支持 Scrapy Playwright 脚本生成

## 💡 使用示例

### 基本使用

```python
from playwright.async_api import async_playwright
from autospider.crawler.url_collector import collect_detail_urls

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        # 收集详情页 URL
        result = await collect_detail_urls(
            page=page,
            list_url="https://example.com/products",
            task_description="采集商品详情页 URL",
            explore_count=3
        )
        
        print(f"收集到 {len(result.collected_urls)} 个详情页 URL")
        print(f"详情页 URL 示例: {result.collected_urls[:3]}")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
```

### 高级使用

```python
from playwright.async_api import async_playwright
from autospider.crawler.url_collector import URLCollector

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        # 创建 URLCollector 实例
        collector = URLCollector(
            page=page,
            list_url="https://example.com/products",
            task_description="采集商品详情页 URL",
            explore_count=5,  # 增加探索数量以提高 XPath 提取准确性
            max_nav_steps=15,  # 增加最大导航步骤
            output_dir="custom_output"  # 自定义输出目录
        )
        
        # 运行收集流程
        result = await collector.run()
        
        # 处理结果
        print(f"探索了 {len(result.detail_visits)} 个详情页")
        print(f"收集到 {len(result.collected_urls)} 个详情页 URL")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
```

## 🔍 最佳实践

### 探索数量设置
- 建议设置为 3-5 个详情页，平衡准确性和效率
- 对于复杂页面，可适当增加探索数量
- 对于简单列表页，可减少探索数量以提高速度

### 任务描述优化
- 尽可能详细描述任务，包括要收集的内容和筛选条件
- 例如："采集所有状态为'进行中'的招标公告详情页 URL"
- 避免模糊描述，如："采集详情页 URL"

### 断点续传使用
- 对于大规模收集任务，建议启用 Redis 持久化
- 中断后重新运行相同命令，自动从断点继续
- 确保任务描述和列表 URL 与之前一致

## 🐛 故障排除

### 问题：探索阶段无法进入详情页

**可能原因**：
1. LLM 无法识别详情页链接
2. 页面结构复杂，元素无法被正确标注
3. 网站有反爬机制，阻止自动化操作

**解决方案**：
1. 优化任务描述，明确指出详情页链接的特征
2. 增加探索尝试次数
3. 调整浏览器配置，模拟真实用户行为

### 问题：无法提取公共 XPath

**可能原因**：
1. 详情页链接的 HTML 结构不一致
2. 探索的详情页数量不足
3. 页面使用动态生成的类名或 ID

**解决方案**：
1. 增加探索的详情页数量
2. 手动调整收集策略，使用 LLM 遍历模式
3. 优化页面扫描参数，提高元素标注准确性

### 问题：收集阶段速度缓慢

**可能原因**：
1. 使用了 LLM 遍历模式而非 XPath 模式
2. 速率控制器配置过于保守
3. 页面加载时间过长

**解决方案**：
1. 增加探索数量，提高 XPath 提取成功率
2. 调整速率控制器参数，增加并发请求数
3. 优化页面加载等待时间配置

## 📚 方法参考

### URLCollector 类方法

| 方法名 | 参数 | 返回值 | 描述 |
|--------|------|--------|------|
| `__init__` | page, list_url, task_description, explore_count=3, max_nav_steps=10, output_dir="output" | None | 初始化 URLCollector 实例 |
| `run` | None | `URLCollectorResult` | 运行完整的 URL 收集流程 |
| `_explore_phase` | None | None | 执行探索阶段 |
| `_collect_phase_with_xpath` | None | None | 使用 XPath 收集 URL |
| `_collect_phase_with_llm` | None | None | 使用 LLM 收集 URL |
| `_save_config` | None | None | 保存配置信息 |
| `_generate_crawler_script` | None | `str` | 生成爬虫脚本 |
| `_create_result` | None | `URLCollectorResult` | 创建结果对象 |
| `_save_result` | result, crawler_script="" | None | 保存结果到文件 |

### 便捷函数

| 函数名 | 参数 | 返回值 | 描述 |
|--------|------|--------|------|
| `collect_detail_urls` | page, list_url, task_description, explore_count=3, output_dir="output" | `URLCollectorResult` | 创建并运行 URLCollector |

## 🔄 依赖关系

- `BaseCollector` - 收集器基类
- `LLMDecider` - LLM 决策器
- `ScriptGenerator` - 脚本生成器
- `ConfigPersistence` - 配置持久化
- `XPathExtractor` - XPath 提取器
- `NavigationHandler` - 导航处理器
- `PaginationHandler` - 分页处理器

## 📝 设计模式

- **协调器模式**：URLCollector 作为协调器，管理各个组件的工作流程
- **策略模式**：支持多种收集策略（XPath 模式、LLM 模式）
- **模板方法模式**：继承自 BaseCollector，重写特定阶段的实现
- **状态模式**：管理不同阶段的状态转换

## 🚀 性能优化

### 时间复杂度
- 探索阶段：O(N * M)，其中 N 是探索数量，M 是每个页面的元素数量
- 收集阶段：O(P * K)，其中 P 是页面数量，K 是每个页面的详情链接数量

### 空间复杂度
- O(N + P)，存储探索记录和收集的 URL

### 优化建议
- 对于大规模收集任务，建议使用分布式架构
- 启用 Redis 持久化，支持断点续传
- 调整速率控制器参数，平衡效率和稳定性

## 📌 版本历史

| 版本 | 更新内容 | 日期 |
|------|----------|------|
| 1.0 | 初始版本 | 2026-01-01 |
| 1.1 | 增加断点续传功能 | 2026-01-10 |
| 1.2 | 优化 XPath 提取算法 | 2026-01-15 |
| 1.3 | 支持多种分页控件处理 | 2026-01-18 |

## 🔮 未来规划

- 支持更多类型的详情页进入方式
- 优化 LLM 决策效率，减少 API 调用次数
- 增加自动防反爬机制
- 支持动态调整探索策略

## 📄 许可证

MIT License

---

最后更新: 2026-01-19