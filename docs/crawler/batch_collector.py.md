# Batch Collector - 批量 URL 收集器

## 📋 基本信息

### 文件路径
`d:\autospider\src\autospider\crawler\batch_collector.py`

### 核心功能
批量爬取器，基于配置文件执行批量 URL 收集，支持断点续爬功能。

### 设计理念
负责流程的第二阶段：读取配置文件，执行批量 URL 收集，支持断点续爬功能。

## 📁 函数目录

### 主类
- `BatchCollector` - 批量爬取器

### 便捷函数
- `batch_collect_urls` - 批量收集 URL 的便捷函数

### 核心方法
- `run` - 运行收集流程（实现基类抽象方法）
- `collect_from_config` - 从配置文件执行批量收集（主流程）
- `_load_config` - 加载配置文件
- `_initialize_handlers` - 初始化各个处理器
- `_resume_to_target_page` - 使用三阶段策略恢复到目标页

## 🎯 核心功能详解

### BatchCollector 类

**功能说明**：批量爬取器，继承自 `BaseCollector`，基于配置文件执行批量 URL 收集。

**初始化参数**：
| 参数名 | 类型 | 描述 | 默认值 |
|--------|------|------|--------|
| page | `Page` | Playwright 页面对象 | 必填 |
| config_path | `str | Path` | 配置文件路径 | 必填 |
| output_dir | `str` | 输出目录 | "output" |

**核心属性**：
| 属性名 | 类型 | 描述 |
|--------|------|------|
| config_path | `Path` | 配置文件路径 |
| collection_config | `CollectionConfig | None` | 收集配置对象 |
| config_persistence | `ConfigPersistence` | 配置持久化管理器 |

### 核心方法

#### run()
**功能**：运行收集流程（实现基类抽象方法），代理到 `collect_from_config()` 方法。

**返回值**：`URLCollectorResult` - 收集结果对象

#### collect_from_config()
**功能**：从配置文件执行批量收集的主流程。

**返回值**：`URLCollectorResult` - 收集结果对象

**执行流程**：
1. 加载配置文件
2. 加载历史进度
3. 导航到列表页
4. 初始化处理器
5. 重放导航步骤
6. 断点恢复（如果需要）
7. 执行收集阶段（XPath 或 LLM 模式）
8. 保存结果

#### _load_config()
**功能**：加载配置文件。

**返回值**：`bool` - 是否加载成功

**执行流程**：
1. 检查配置文件是否存在
2. 读取配置文件内容
3. 解析配置数据
4. 提取配置信息到实例属性

#### _initialize_handlers()
**功能**：初始化各个处理器（覆盖基类方法以添加 LLM 支持）。

**执行流程**：
1. 调用基类初始化方法
2. 如果没有公共 XPath，初始化 LLM 决策器
3. 初始化导航处理器
4. 更新分页处理器配置

#### _resume_to_target_page()
**功能**：使用三阶段策略恢复到目标页（覆盖基类以使用配置中的 XPath）。

**参数**：
| 参数名 | 类型 | 描述 |
|--------|------|------|
| target_page_num | `int` | 目标页码 |
| jump_widget_xpath | `dict[str, str] | None` | 跳转控件 XPath |
| pagination_xpath | `str | None` | 分页控件 XPath |

**返回值**：`int` - 实际到达的页码

### batch_collect_urls() 便捷函数

**功能**：创建并运行 BatchCollector 的便捷函数。

**参数**：
| 参数名 | 类型 | 描述 |
|--------|------|------|
| page | `Page` | Playwright 页面对象 |
| config_path | `str | Path` | 配置文件路径 |
| output_dir | `str` | 输出目录 |

**返回值**：`URLCollectorResult` - 收集结果对象

## 🚀 特性说明

### 基于配置的批量收集
- 从配置文件读取列表页 URL、任务描述、导航步骤和公共 XPath
- 支持灵活的配置格式，便于与其他模块集成
- 配置文件支持 JSON 格式，易于管理和版本控制

### 断点续传功能
- 支持从上次中断的页码继续收集
- 自动加载历史进度和收集的 URL
- 支持 Redis 和本地文件双重持久化

### 灵活的收集策略
- 支持 XPath 模式：使用配置的公共 XPath 高效收集
- 支持 LLM 模式：当没有配置公共 XPath 时，自动切换到 LLM 模式
- 自动降级机制：确保在各种情况下都能继续收集

### 智能导航处理
- 支持重放导航步骤，自动执行筛选操作
- 智能处理导航失败情况
- 支持多种导航控件和交互方式

## 💡 使用示例

### 基本使用

```python
from playwright.async_api import async_playwright
from autospider.crawler.batch_collector import batch_collect_urls

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        # 批量收集 URL
        result = await batch_collect_urls(
            page=page,
            config_path="output/config.json",
            output_dir="output"
        )
        
        print(f"收集到 {len(result.collected_urls)} 个详情页 URL")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
```

### 高级使用

```python
from playwright.async_api import async_playwright
from autospider.crawler.batch_collector import BatchCollector

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        # 创建批量收集器实例
        collector = BatchCollector(
            page=page,
            config_path="output/config.json",
            output_dir="custom_output"
        )
        
        # 运行收集流程
        result = await collector.collect_from_config()
        
        print(f"收集到 {len(result.collected_urls)} 个详情页 URL")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
```

## 🔍 最佳实践

### 配置文件管理

- 确保配置文件格式正确，包含所有必要字段
- 定期备份配置文件，避免配置丢失
- 对于不同的收集任务，使用不同的配置文件

### 断点续传使用

- 对于大规模收集任务，建议启用 Redis 持久化
- 中断后重新运行相同命令，自动从断点继续
- 确保配置文件路径和输出目录与之前一致

### 性能优化

- 优先使用 XPath 模式，提高收集效率
- 合理设置速率控制参数，平衡效率和稳定性
- 对于大规模收集任务，考虑使用分布式部署

## 🐛 故障排除

### 问题：配置文件加载失败

**可能原因**：
1. 配置文件不存在
2. 配置文件格式错误
3. 配置文件缺少必要字段

**解决方案**：
1. 检查配置文件路径是否正确
2. 验证配置文件格式是否为有效的 JSON
3. 确保配置文件包含所有必要字段（list_url、task_description 等）

### 问题：导航步骤重放失败

**可能原因**：
1. 页面结构发生变化
2. 导航步骤中的元素无法找到
3. 网站有反爬机制，阻止自动化操作

**解决方案**：
1. 重新生成导航步骤
2. 调整导航步骤，使用更稳定的定位方式
3. 增加延迟和随机波动，模拟真实用户行为

### 问题：收集阶段速度缓慢

**可能原因**：
1. 使用了 LLM 模式而非 XPath 模式
2. 速率控制器配置过于保守
3. 页面加载时间过长

**解决方案**：
1. 确保配置了有效的公共 XPath
2. 调整速率控制器参数，增加并发请求数
3. 优化页面加载等待时间配置

## 📚 方法参考

### BatchCollector 类方法

| 方法名 | 参数 | 返回值 | 描述 |
|--------|------|--------|------|
| `run` | None | `URLCollectorResult` | 运行收集流程 |
| `collect_from_config` | None | `URLCollectorResult` | 从配置文件执行批量收集 |
| `_load_config` | None | `bool` | 加载配置文件 |
| `_initialize_handlers` | None | None | 初始化各个处理器 |
| `_resume_to_target_page` | target_page_num, jump_widget_xpath=None, pagination_xpath=None | `int` | 使用三阶段策略恢复到目标页 |
| `_create_result` | None | `URLCollectorResult` | 创建收集结果 |
| `_create_empty_result` | None | `URLCollectorResult` | 创建空收集结果 |
| `_save_result` | result | None | 保存结果到文件 |

### 便捷函数

| 函数名 | 参数 | 返回值 | 描述 |
|--------|------|--------|------|
| `batch_collect_urls` | page, config_path, output_dir="output" | `URLCollectorResult` | 批量收集 URL 的便捷函数 |

## 🔄 依赖关系

- `BaseCollector` - 收集器基类
- `CollectionConfig` - 收集配置对象
- `ConfigPersistence` - 配置持久化管理器
- `LLMDecisionMaker` - LLM 决策器
- `NavigationHandler` - 导航处理器
- `LLMDecider` - LLM 决策器

## 📝 设计模式

- **继承模式**：继承自 BaseCollector，复用公共逻辑
- **策略模式**：支持多种收集策略（XPath 模式、LLM 模式）
- **模板方法模式**：定义收集流程的骨架，子类实现具体步骤
- **代理模式**：run 方法代理到 collect_from_config 方法

## 🚀 性能优化

### 时间复杂度
- XPath 收集模式：O(P * K)，其中 P 是页面数量，K 是每个页面的详情链接数量
- LLM 收集模式：O(P * S * M)，其中 P 是页面数量，S 是滚动次数，M 是每个页面的元素数量

### 空间复杂度
- O(N)，其中 N 是收集的 URL 数量

### 优化建议

1. **优先使用 XPath 模式**：XPath 模式比 LLM 模式高效得多
2. **合理设置速率控制参数**：根据网站响应情况动态调整延迟
3. **启用 Redis 持久化**：对于大规模收集任务，Redis 比本地文件更高效
4. **优化配置文件**：确保配置文件包含有效的公共 XPath

## 📌 版本历史

| 版本 | 更新内容 | 日期 |
|------|----------|------|
| 1.0 | 初始版本 | 2026-01-01 |
| 1.1 | 增加断点续传功能 | 2026-01-10 |
| 1.2 | 支持 LLM 模式 | 2026-01-15 |
| 1.3 | 优化导航步骤重放 | 2026-01-18 |

## 🔮 未来规划

- 支持更多类型的配置文件格式
- 优化配置文件验证机制
- 增加配置文件生成器
- 支持分布式批量收集
- 提供更详细的收集统计信息

## 📄 许可证

MIT License

---

最后更新: 2026-01-19