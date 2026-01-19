# Config Generator - 配置生成器

## 📋 基本信息

### 文件路径
`d:\autospider\src\autospider\extractor\config_generator.py`

### 核心功能
配置生成器，通过 LLM 探索网站，生成包含导航步骤、XPath 定位等信息的爬取配置文件。

### 设计理念
负责流程的第一阶段：通过 LLM 探索网站，生成包含导航步骤、XPath 定位等信息的配置文件 `collection_config.json`。

## 📁 函数目录

### 主类
- `ConfigGenerator` - 配置生成器

### 便捷函数
- `generate_collection_config` - 生成爬取配置的便捷函数

### 核心方法
- `generate_config` - 生成配置文件（主流程）
- `_initialize_handlers` - 初始化各个处理器
- `_explore_phase` - 探索阶段：进入多个详情页
- `_handle_current_is_detail` - 处理当前页面就是详情页的情况
- `_handle_select_detail_links` - 处理选择详情链接的情况
- `_handle_click_to_enter` - 处理点击进入详情页的情况

## 🎯 核心功能详解

### ConfigGenerator 类

**功能说明**：配置生成器，通过探索网站生成爬取配置文件，包括导航步骤、详情页 XPath 定位、分页控件 XPath 和跳转控件 XPath。

**初始化参数**：
| 参数名 | 类型 | 描述 | 默认值 |
|--------|------|------|--------|
| page | `Page` | Playwright 页面对象 | 必填 |
| list_url | `str` | 列表页 URL | 必填 |
| task_description | `str` | 任务描述 | 必填 |
| explore_count | `int` | 探索详情页的数量 | 3 |
| max_nav_steps | `int` | 最大导航步骤数 | 10 |
| output_dir | `str` | 输出目录 | "output" |

**核心属性**：
| 属性名 | 类型 | 描述 |
|--------|------|------|
| detail_visits | `list[DetailPageVisit]` | 详情页访问记录 |
| visited_detail_urls | `set[str]` | 已访问的详情页 URL 集合 |
| nav_steps | `list[dict]` | 导航步骤列表 |
| common_detail_xpath | `str | None` | 详情页公共 XPath |
| decider | `LLMDecider` | LLM 决策器 |
| xpath_extractor | `XPathExtractor` | XPath 提取器 |
| url_extractor | `URLExtractor` | URL 提取器 |
| llm_decision_maker | `LLMDecisionMaker` | LLM 决策制定器 |
| navigation_handler | `NavigationHandler` | 导航处理器 |
| pagination_handler | `PaginationHandler` | 分页处理器 |
| config_persistence | `ConfigPersistence` | 配置持久化管理器 |

### 核心方法

#### generate_config()
**功能**：生成配置文件的主流程。

**返回值**：`CollectionConfig` - 生成的配置对象

**执行流程**：
1. 导航到列表页
2. 初始化处理器
3. 执行导航阶段（筛选操作）
4. 执行探索阶段（进入详情页）
5. 提取公共 XPath
6. 提取分页控件
7. 提取跳转控件
8. 创建并保存配置

#### _initialize_handlers()
**功能**：初始化各个处理器。

**执行流程**：
1. 初始化 LLMDecisionMaker
2. 初始化 NavigationHandler
3. 初始化 PaginationHandler

#### _explore_phase()
**功能**：探索阶段，进入多个详情页。

**执行流程**：
1. 扫描页面
2. 调用 LLM 决策
3. 处理决策结果（进入详情页、选择链接等）
4. 记录详情页访问信息
5. 返回列表页继续探索

#### _handle_current_is_detail()
**功能**：处理当前页面就是详情页的情况。

**参数**：
| 参数名 | 类型 | 描述 |
|--------|------|------|
| explored | `int` | 已探索的详情页数量 |

**返回值**：`bool` - 是否成功探索

#### _handle_select_detail_links()
**功能**：处理选择详情链接的情况。

**参数**：
| 参数名 | 类型 | 描述 |
|--------|------|------|
| llm_decision | `dict` | LLM 决策结果 |
| snapshot | `SoMSnapshot` | 页面快照 |
| screenshot_base64 | `str` | 截图 Base64 |
| explored | `int` | 已探索的详情页数量 |

**返回值**：`int` - 新探索的详情页数量

#### _handle_click_to_enter()
**功能**：处理点击进入详情页的情况。

**参数**：
| 参数名 | 类型 | 描述 |
|--------|------|------|
| llm_decision | `dict` | LLM 决策结果 |
| snapshot | `SoMSnapshot` | 页面快照 |

**返回值**：`bool` - 是否成功进入详情页

### generate_collection_config() 便捷函数

**功能**：生成爬取配置的便捷函数。

**参数**：同 ConfigGenerator 初始化参数

**返回值**：`CollectionConfig` - 生成的配置对象

## 🚀 特性说明

### 智能探索机制
- 自动进入多个详情页，记录操作步骤
- 支持多种进入详情页的方式（直接点击、选择链接等）
- 自动处理页面滚动和加载

### 导航步骤生成
- 根据任务描述自动执行筛选操作
- 记录详细的导航步骤
- 支持复杂的筛选条件

### XPath 自动提取
- 自动提取详情页的公共 XPath
- 支持多种 XPath 提取策略
- 生成稳定的定位器

### 分页控件处理
- 自动识别和提取分页控件 XPath
- 支持多种分页控件类型
- 智能处理分页逻辑

### 跳转控件支持
- 提取跳转控件 XPath，用于断点恢复
- 支持多种跳转控件类型
- 提高断点恢复的准确性

### 配置持久化
- 自动保存生成的配置文件
- 支持配置文件的加载和使用
- 便于后续批量收集

## 💡 使用示例

### 基本使用

```python
from playwright.async_api import async_playwright
from autospider.extractor.config_generator import ConfigGenerator

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        # 创建配置生成器实例
        generator = ConfigGenerator(
            page=page,
            list_url="https://example.com/products",
            task_description="采集商品详情页 URL",
            explore_count=3,
            output_dir="output"
        )
        
        # 生成配置
        config = await generator.generate_config()
        
        # 打印配置信息
        print(f"导航步骤: {len(config.nav_steps)} 个")
        print(f"详情页 XPath: {config.common_detail_xpath}")
        print(f"分页控件 XPath: {config.pagination_xpath}")
        print(f"跳转控件 XPath: {config.jump_widget_xpath}")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
```

### 使用便捷函数

```python
from playwright.async_api import async_playwright
from autospider.extractor.config_generator import generate_collection_config

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        # 使用便捷函数生成配置
        config = await generate_collection_config(
            page=page,
            list_url="https://example.com/products",
            task_description="采集商品详情页 URL",
            explore_count=3,
            output_dir="output"
        )
        
        # 打印配置信息
        print(f"配置生成成功，导航步骤: {len(config.nav_steps)} 个")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
```

## 🔍 最佳实践

### 任务描述优化
- 尽可能详细描述任务，包括要收集的内容和筛选条件
- 例如："采集所有状态为'进行中'的招标公告详情页 URL"
- 避免模糊描述，如："采集详情页 URL"

### 探索数量设置
- 建议设置为 3-5 个详情页，平衡准确性和效率
- 对于复杂页面，可适当增加探索数量
- 对于简单列表页，可减少探索数量以提高速度

### 导航步骤管理
- 合理设置最大导航步骤数，避免无限导航
- 导航步骤会影响后续的 XPath 提取准确性
- 复杂的筛选操作可能需要更多的导航步骤

### 输出目录设置
- 为不同的任务设置不同的输出目录
- 便于管理和查看生成的配置和截图
- 建议使用有意义的目录名称

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
2. 优化页面扫描参数，提高元素标注准确性
3. 手动调整收集策略

### 问题：导航步骤执行失败

**可能原因**：
1. 页面结构发生变化
2. 导航步骤中的元素无法找到
3. 网站有反爬机制，阻止自动化操作

**解决方案**：
1. 重新生成导航步骤
2. 调整导航步骤，使用更稳定的定位方式
3. 增加延迟和随机波动，模拟真实用户行为

## 📚 方法参考

### ConfigGenerator 类方法

| 方法名 | 参数 | 返回值 | 描述 |
|--------|------|--------|------|
| `generate_config` | None | `CollectionConfig` | 生成配置文件（主流程） |
| `_initialize_handlers` | None | None | 初始化各个处理器 |
| `_explore_phase` | None | None | 探索阶段：进入多个详情页 |
| `_handle_current_is_detail` | explored | `bool` | 处理当前页面就是详情页的情况 |
| `_handle_select_detail_links` | llm_decision, snapshot, screenshot_base64, explored | `int` | 处理选择详情链接的情况 |
| `_handle_click_to_enter` | llm_decision, snapshot | `bool` | 处理点击进入详情页的情况 |
| `_create_empty_config` | None | `CollectionConfig` | 创建空配置（探索失败时） |

### 便捷函数

| 函数名 | 参数 | 返回值 | 描述 |
|--------|------|--------|------|
| `generate_collection_config` | page, list_url, task_description, explore_count=3, output_dir="output" | `CollectionConfig` | 生成爬取配置的便捷函数 |

## 🔄 依赖关系

- `LLMDecider` - LLM 决策器
- `XPathExtractor` - XPath 提取器
- `URLExtractor` - URL 提取器
- `LLMDecisionMaker` - LLM 决策制定器
- `NavigationHandler` - 导航处理器
- `PaginationHandler` - 分页处理器
- `ConfigPersistence` - 配置持久化管理器

## 📝 设计模式

- **协调器模式**：ConfigGenerator 作为协调器，管理各个处理器的工作流程
- **策略模式**：支持多种探索和收集策略
- **模板方法模式**：定义配置生成的骨架，具体实现由子类或处理器完成
- **观察者模式**：进度变化时通知持久化管理器

## 🚀 性能优化

### 时间复杂度
- 探索阶段：O(N * M)，其中 N 是探索数量，M 是每个页面的元素数量
- XPath 提取：O(N * K)，其中 N 是详情页数量，K 是每个页面的元素数量

### 空间复杂度
- O(N + P)，其中 N 是收集的 URL 数量，P 是生成的截图数量

### 优化建议

1. **合理设置探索数量**：平衡准确性和效率
2. **使用文本优先的 mark_id 解析**：避免 LLM 读错编号导致误点
3. **限制连续滚动次数**：防止无限滚动
4. **缓存已访问的详情页 URL**：避免重复访问
5. **优化 LLM 调用频率**：减少不必要的 API 调用

## 📌 版本历史

| 版本 | 更新内容 | 日期 |
|------|----------|------|
| 1.0 | 初始版本 | 2026-01-01 |
| 1.1 | 增加文本优先的 mark_id 解析 | 2026-01-10 |
| 1.2 | 优化探索阶段逻辑 | 2026-01-15 |
| 1.3 | 支持跳转控件 XPath 提取 | 2026-01-18 |
| 1.4 | 优化配置持久化 | 2026-01-19 |

## 🔮 未来规划

- 支持更多类型的页面结构
- 优化 XPath 提取算法
- 增加配置验证功能
- 支持配置的可视化编辑
- 提供更详细的配置分析报告

## 📄 许可证

MIT License

---

最后更新: 2026-01-19