# BaseCollector - 收集器基类

## 📋 基本信息

### 文件路径
`d:\autospider\src\autospider\crawler\base_collector.py`

### 核心功能
收集器基类，抽取 URLCollector 和 BatchCollector 的公共逻辑，提供统一的速率控制、断点续爬、Redis 持久化、XPath/LLM 收集和分页处理功能。

### 设计理念
采用抽象基类设计，将公共逻辑抽取到基类中，减少代码重复，提高可维护性。子类只需实现特定的业务逻辑即可。

## 📁 函数目录

### 主类
- `BaseCollector` - URL 收集器基类

### 核心方法
- `run` - 运行收集流程（抽象方法，子类实现）
- `_collect_phase_with_xpath` - 使用公共 XPath 收集 URL
- `_collect_phase_with_llm` - 使用 LLM 遍历列表页收集 URL
- `_extract_urls_with_xpath` - 使用 XPath 提取当前页的 URL
- `_collect_page_with_llm` - 使用 LLM 收集单页的 URL
- `_resume_to_target_page` - 使用三阶段策略恢复到目标页

### 辅助方法
- `_init_redis_manager` - 初始化 Redis 管理器
- `_initialize_handlers` - 初始化各个处理器
- `_sync_page_references` - 同步页面引用到各处理器
- `_is_progress_compatible` - 检查进度是否与当前任务匹配
- `_load_previous_urls` - 加载历史 URL
- `_save_progress` - 保存收集进度
- `_append_new_urls_to_progress` - 将新增 URL 增量追加到 urls.txt
- `_create_result` - 创建收集结果

## 🎯 核心功能详解

### BaseCollector 类

**功能说明**：URL 收集器基类，提供公共的收集逻辑，包括速率控制、断点续爬、Redis 持久化、XPath/LLM 收集和分页处理。

**初始化参数**：
| 参数名 | 类型 | 描述 | 默认值 |
|--------|------|------|--------|
| page | `Page` | Playwright 页面对象 | 必填 |
| list_url | `str` | 列表页 URL | 必填 |
| task_description | `str` | 任务描述 | 必填 |
| output_dir | `str` | 输出目录 | "output" |

**核心属性**：
| 属性名 | 类型 | 描述 |
|--------|------|------|
| collected_urls | `list[str]` | 已收集的 URL 列表 |
| rate_controller | `AdaptiveRateController` | 自适应速率控制器 |
| progress_persistence | `ProgressPersistence` | 进度持久化管理器 |
| redis_manager | `RedisManager | None` | Redis 管理器（可选） |

### 核心方法

#### run()
**功能**：运行收集流程（抽象方法，子类实现）。

**返回值**：`URLCollectorResult` - 收集结果对象

#### _collect_phase_with_xpath()
**功能**：使用公共 XPath 直接提取 URL，高效遍历列表页。

**执行流程**：
1. 检查当前页码，断点恢复时直接从当前页面继续
2. 应用速率控制延迟
3. 使用 XPath 提取 URL
4. 记录收集结果
5. 保存进度
6. 尝试翻页，继续收集

#### _collect_phase_with_llm()
**功能**：使用 LLM 遍历列表页，当无法提取公共 XPath 时使用。

**执行流程**：
1. 检查当前页码，断点恢复时直接从当前页面继续
2. 应用速率控制延迟
3. 使用 LLM 识别和收集 URL
4. 记录收集结果
5. 保存进度
6. 尝试翻页，继续收集

#### _extract_urls_with_xpath()
**功能**：使用 XPath 提取当前页的 URL。

**返回值**：`bool` - 是否成功提取到新 URL

**执行流程**：
1. 使用 XPath 定位所有详情链接
2. 优先尝试从 href 属性获取 URL
3. 若 href 获取失败，尝试点击元素获取 URL
4. 将新 URL 添加到收集列表
5. 保存到 Redis（如果启用）

#### _collect_page_with_llm()
**功能**：使用 LLM 收集单页的 URL。

**参数**：
| 参数名 | 类型 | 描述 |
|--------|------|------|
| max_scrolls | `int` | 最大滚动次数 |
| no_new_threshold | `int` | 连续无新 URL 的阈值 |

**返回值**：`bool` - 是否成功收集到新 URL

**执行流程**：
1. 扫描页面获取 SoM 快照
2. 调用 LLM 识别详情链接
3. 提取并保存 URL
4. 检查是否有新 URL
5. 滚动页面，继续收集

#### _resume_to_target_page()
**功能**：使用三阶段策略恢复到目标页，支持断点续爬。

**参数**：
| 参数名 | 类型 | 描述 |
|--------|------|------|
| target_page_num | `int` | 目标页码 |
| jump_widget_xpath | `dict[str, str] | None` | 跳转控件 XPath |
| pagination_xpath | `str | None` | 分页控件 XPath |

**返回值**：`int` - 实际到达的页码

## 🚀 特性说明

### 速率控制机制
- 自适应速率控制器，根据收集结果动态调整延迟
- 支持成功记录和失败惩罚
- 可配置基础延迟和延迟范围

### 断点续传功能
- 支持从上次中断的页码继续收集
- 自动加载历史 URL，避免重复收集
- 使用 ResumeCoordinator 实现三阶段恢复策略
- 支持 Redis 和本地文件双重持久化

### 灵活的收集策略
- 支持 XPath 模式：高效遍历列表页
- 支持 LLM 模式：智能识别详情链接
- 自动降级机制：当 XPath 提取失败时，自动切换到 LLM 模式

### 智能分页处理
- 支持多种分页控件：数字页码、下一页按钮、跳转组件
- 自动识别当前页码和目标页
- 智能处理分页失败情况

### Redis 持久化
- 可选的 Redis 支持，用于大规模收集任务
- 实时保存收集的 URL
- 支持分布式部署

## 💡 使用示例

### 继承 BaseCollector 实现自定义收集器

```python
from autospider.crawler.base_collector import BaseCollector
from autospider.extractor.collector import URLCollectorResult

class CustomCollector(BaseCollector):
    async def run(self) -> URLCollectorResult:
        """运行自定义收集流程"""
        print("开始自定义收集流程")
        
        # 1. 初始化处理器
        self._initialize_handlers()
        
        # 2. 导航到列表页
        await self.page.goto(self.list_url, wait_until="domcontentloaded")
        await asyncio.sleep(1)
        
        # 3. 执行自定义导航逻辑
        # ...
        
        # 4. 收集阶段
        if self.common_detail_xpath:
            await self._collect_phase_with_xpath()
        else:
            await self._collect_phase_with_llm()
        
        # 5. 保存结果
        result = self._create_result()
        return result
```

### 使用断点续传功能

```python
from playwright.async_api import async_playwright
from autospider.crawler.url_collector import URLCollector

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        # 创建收集器实例
        collector = URLCollector(
            page=page,
            list_url="https://example.com/products",
            task_description="采集商品详情页 URL"
        )
        
        # 运行收集流程（自动支持断点续传）
        result = await collector.run()
        
        print(f"收集到 {len(result.collected_urls)} 个 URL")
        
        await browser.close()
```

## 🔍 最佳实践

### 子类实现建议

1. **重写 _initialize_handlers 方法**：根据需要初始化额外的处理器
2. **实现 run 方法**：定义具体的收集流程
3. **利用现有方法**：尽量复用基类提供的方法，减少代码重复
4. **保持一致性**：遵循基类的设计模式和命名规范

### 速率控制配置

- 根据网站响应情况调整基础延迟
- 对于敏感网站，增加基础延迟和随机波动范围
- 监控速率控制器日志，根据实际情况调整参数

### 断点续传使用

- 对于大规模收集任务，建议启用 Redis 持久化
- 确保任务描述和列表 URL 与之前一致
- 定期检查进度文件，确保数据正确保存

## 🐛 故障排除

### 问题：断点续传失效

**可能原因**：
1. 任务描述或列表 URL 发生变化
2. Redis 连接失败
3. 进度文件损坏

**解决方案**：
1. 确保任务描述和列表 URL 与之前一致
2. 检查 Redis 配置和连接状态
3. 手动删除旧的进度文件，重新开始

### 问题：速率控制过于保守

**可能原因**：
1. 基础延迟设置过高
2. 惩罚机制过于严格
3. 连续失败次数过多

**解决方案**：
1. 调整基础延迟参数
2. 修改速率控制器配置
3. 检查网站是否有反爬机制

### 问题：XPath 提取失败

**可能原因**：
1. 页面结构发生变化
2. XPath 表达式不正确
3. 元素被动态加载或隐藏

**解决方案**：
1. 重新探索详情页，提取新的 XPath
2. 检查 XPath 表达式语法
3. 增加等待时间，确保元素完全加载

## 📚 方法参考

### 核心方法

| 方法名 | 参数 | 返回值 | 描述 |
|--------|------|--------|------|
| `_collect_phase_with_xpath` | None | None | 使用公共 XPath 收集 URL |
| `_collect_phase_with_llm` | None | None | 使用 LLM 遍历列表页收集 URL |
| `_extract_urls_with_xpath` | None | `bool` | 使用 XPath 提取当前页的 URL |
| `_collect_page_with_llm` | max_scrolls, no_new_threshold | `bool` | 使用 LLM 收集单页的 URL |
| `_resume_to_target_page` | target_page_num, jump_widget_xpath=None, pagination_xpath=None | `int` | 使用三阶段策略恢复到目标页 |

### 辅助方法

| 方法名 | 参数 | 返回值 | 描述 |
|--------|------|--------|------|
| `_init_redis_manager` | None | None | 初始化 Redis 管理器 |
| `_initialize_handlers` | None | None | 初始化各个处理器 |
| `_sync_page_references` | page, list_url=None | None | 同步页面引用到各处理器 |
| `_is_progress_compatible` | progress | `bool` | 检查进度是否与当前任务匹配 |
| `_load_previous_urls` | None | None | 加载历史 URL |
| `_save_progress` | None | None | 保存收集进度 |
| `_append_new_urls_to_progress` | None | None | 将新增 URL 增量追加到 urls.txt |
| `_create_result` | None | `URLCollectorResult` | 创建收集结果 |

## 🔄 依赖关系

- `AdaptiveRateController` - 自适应速率控制器
- `ResumeCoordinator` - 断点恢复协调器
- `ProgressPersistence` - 进度持久化管理器
- `URLExtractor` - URL 提取器
- `LLMDecisionMaker` - LLM 决策器
- `NavigationHandler` - 导航处理器
- `PaginationHandler` - 分页处理器
- `RedisManager` - Redis 管理器（可选）

## 📝 设计模式

- **抽象基类模式**：定义公共接口和默认实现，子类只需实现特定方法
- **策略模式**：支持多种收集策略（XPath 模式、LLM 模式）
- **模板方法模式**：定义收集流程的骨架，子类实现具体步骤
- **装饰器模式**：通过速率控制器动态调整延迟
- **观察者模式**：进度变化时通知持久化管理器

## 🚀 性能优化

### 时间复杂度
- XPath 收集模式：O(P * K)，其中 P 是页面数量，K 是每个页面的详情链接数量
- LLM 收集模式：O(P * S * M)，其中 P 是页面数量，S 是滚动次数，M 是每个页面的元素数量

### 空间复杂度
- O(N)，其中 N 是收集的 URL 数量

### 优化建议

1. **优先使用 XPath 模式**：XPath 模式比 LLM 模式高效得多
2. **合理设置探索数量**：增加探索数量可以提高 XPath 提取的准确性
3. **启用 Redis 持久化**：对于大规模收集任务，Redis 比本地文件更高效
4. **调整速率控制参数**：根据网站响应情况动态调整延迟
5. **优化分页处理**：减少不必要的翻页尝试

## 📌 版本历史

| 版本 | 更新内容 | 日期 |
|------|----------|------|
| 1.0 | 初始版本 | 2026-01-01 |
| 1.1 | 增加断点续传功能 | 2026-01-10 |
| 1.2 | 优化速率控制算法 | 2026-01-15 |
| 1.3 | 支持 Redis 持久化 | 2026-01-18 |

## 🔮 未来规划

- 支持更多类型的持久化存储
- 优化 LLM 调用频率，减少成本
- 增加自动防反爬机制
- 支持动态调整收集策略
- 提供更详细的性能监控

## 📄 许可证

MIT License

---

最后更新: 2026-01-19