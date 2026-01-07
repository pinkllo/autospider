# Crawler 模块

Crawler 模块是 AutoSpider 的核心爬取引擎，负责执行批量网页数据采集任务。该模块集成了 URL 收集、批量爬取、断点续传、速率控制等关键功能，支持从列表页自动发现并导航到详情页，实现全流程自动化的数据采集。

## 模块结构

```
crawler/
├── __init__.py          # 模块入口，导出 BatchCollector 和 URLCollector
├── url_collector.py     # URL 收集器，负责从列表页发现详情页 URL
├── batch_collector.py   # 批量爬取控制器，协调整个爬取流程
└── checkpoint/          # 断点续传系统
    ├── __init__.py      # 检查点模块导出
    ├── rate_controller.py   # 自适应速率控制器
    └── resume_strategy.py   # 断点恢复策略
```

## 核心组件

### URLCollector

URLCollector 是负责从列表页收集详情页 URL 的专用组件。它通过多阶段探索策略，自动发现并导航到目标详情页，同时进行 URL 去重和持久化存储。该组件特别适用于需要从列表页面批量采集详情链接的场景，例如电商商品列表、新闻文章列表、论坛帖子列表等。

URLCollector 的工作流程分为三个主要阶段：导航阶段负责将浏览器定位到列表页并初始化各类处理器；探索阶段按照预设数量依次访问详情页，收集页面信息；分析阶段根据探索结果确定详情页的公共 XPath 模式，并进行批量收集。整个过程支持断点续传，每次收集的 URL 会实时保存到 Redis 或内存中，即使中途失败也能从断点恢复。

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

URLCollector 初始化时需要传入列表页 URL 和任务描述，explore_count 参数控制探索阶段采样的详情页数量，common_detail_xpath 可选参数用于指定详情页的公共 XPath 路径，redis_manager 参数支持 Redis 持久化以实现断点续传功能。

### BatchCollector

BatchCollector 是批量爬取的主控制器，负责协调整个采集流程的各个环节。它从配置文件加载爬取策略，依次执行列表页导航、分页探索、详情页收集等步骤，并在每个阶段进行进度跟踪和错误处理。BatchCollector 的设计目标是让用户只需配置好采集规则，即可一键启动完整的批量采集任务。

BatchCollector 的核心流程包括配置加载、列表页导航、分页探索、详情页收集四个主要阶段。在配置加载阶段，它读取并解析 YAML 配置文件，提取列表页 URL、任务描述、导航步骤等关键信息。列表页导航阶段负责将浏览器定位到起始页面，并根据需要进行登录、验证等前置操作。分页探索阶段通过模拟翻页操作，收集足够多的详情页样本，用于分析详情页的公共特征。最后的详情页收集阶段利用前述分析结果，批量访问所有详情页并提取数据。

```python
from autospider import BatchCollector

collector = BatchCollector(
    config_path="./config.yaml",
    redis_manager=redis_manager
)

result = await collector.collect_from_config()
```

## 断点续传系统

断点续传系统是 AutoSpider 的核心特性之一，它确保长时间运行的采集任务不会因为网络故障、程序异常等原因而完全失败重来。该系统由三个核心组件构成：速率控制器（AdaptiveRateController）负责智能调节请求频率，URL 存储器（Redis）负责持久化已收集的 URL，恢复策略（ResumeStrategy）负责在中断后快速恢复到目标进度。

### AdaptiveRateController

AdaptiveRateController 实现了自适应速率控制算法，能够根据网站的反爬策略自动调整请求频率。当检测到访问被拒绝或出现其他异常信号时，控制器会自动增加请求间隔；当连续多个请求成功后，系统会逐步恢复正常的请求速率。这种动态调节机制既能有效避免触发网站的反爬机制，又能最大化采集效率。

控制器的核心算法基于指数退避策略。当前延迟时间计算公式为：delay = base_delay × (backoff_factor ^ level)，其中 base_delay 是基础延迟，backoff_factor 是退避因子，level 是当前降速等级。每次触发惩罚时，level 增加 1；每成功处理 credit_recovery_pages 个页面后，level 减少 1。这种设计确保了系统在遇到反爬时能快速响应，在情况好转时又能及时恢复速度。

```python
from autospider.checkpoint import AdaptiveRateController

controller = AdaptiveRateController(
    base_delay=1.0,      # 基础延迟 1 秒
    backoff_factor=1.5,  # 退避因子 1.5
    max_level=5,         # 最大降速等级 5
    credit_recovery_pages=10,  # 每 10 个成功请求恢复一级
    initial_level=0      # 初始等级 0
)

# 获取当前延迟
delay = controller.get_delay()

# 触发惩罚（遇到反爬）
controller.apply_penalty()

# 记录成功
controller.record_success()

# 从检查点恢复
controller.set_level(3)
```

### ResumeStrategy

ResumeStrategy 定义了断点恢复的策略接口，目前提供了三种具体的恢复策略实现。URLPatternStrategy 适用于 URL 包含页码参数的网站，通过直接构造目标页的 URL 实现快速跳转。WidgetJumpStrategy 适用于使用页码输入控件的网站，通过模拟输入页码并点击确定按钮来跳转。SmartSkipStrategy 是兜底方案，它从第一页开始逐页快速检测，只在检测到新数据时回退一页，确保数据完整性。

```python
from autospider.checkpoint import (
    ResumeCoordinator,
    URLPatternStrategy,
    WidgetJumpStrategy,
    SmartSkipStrategy
)

# 使用 URL 规律爆破策略
strategy = URLPatternStrategy(list_url="https://example.com/list?page=1")

# 使用控件直达策略
widget_strategy = WidgetJumpStrategy(
    jump_widget_xpath={
        "input": "input.page-input",
        "button": "button.go-btn"
    }
)

# 使用智能跳过策略
smart_strategy = SmartSkipStrategy(
    list_url="https://example.com/list",
    item_xpath="//div[@class='product-item']",
    nav_steps=[...]
)

# 协调器自动选择最佳策略
coordinator = ResumeCoordinator([strategy, widget_strategy, smart_strategy])
result = await coordinator.try_resume(page, target_page=50)
```

## 配置选项

Crawler 模块支持通过配置文件进行详细的行为定制。配置项分为基础设置、延迟控制、退避策略和采集策略四大类，每类配置都有合理的默认值，用户只需覆盖需要自定义的选项即可。

### 基础设置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| explore_count | 3 | 探索阶段采样的详情页数量 |
| check_interval | 0.5 | 翻页后检查页面变化的间隔时间（秒）|
| max_retry | 3 | 页面访问失败后的最大重试次数 |
| goto_timeout | 30000 | 页面导航超时时间（毫秒）|

### 延迟控制

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| action_delay_base | 1.0 | 基础延迟时间（秒）|
| action_delay_random | 1.0 | 随机延迟浮动范围（秒）|
| nav_step_delay_base | 2.0 | 导航步骤间的基础延迟（秒）|
| nav_step_delay_random | 1.0 | 导航步骤间的随机延迟（秒）|

### 退避策略

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| backoff_factor | 1.5 | 降速退避因子 |
| max_backoff_level | 5 | 最大降速等级 |
| credit_recovery_pages | 10 | 连续成功多少页后恢复一级 |
| max_credit | 100 | 最大信用值 |

### 采集策略

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| max_pages_per_run | 100 | 单次运行最大采集页数 |
| max_total_pages | 1000 | 总共最大采集页数 |
| url_dedup_enabled | True | 是否启用 URL 去重 |
| checkpoint_interval | 10 | 检查点保存间隔（页数）|

## 完整配置示例

```yaml
crawler:
  # 列表页 URL
  list_url: "https://example.com/products"

  # 任务描述
  task_description: "采集商品名称、价格和详情"

  # 导航步骤（用于翻页操作）
  nav_steps:
    - action: "scroll"
      direction: "down"
      times: 2
    - action: "click"
      selector: "button.next-page"

  # 详情页的通用 XPath（可选，自动探测）
  common_detail_xpath: "//a[@class='product-link']/@href"

  # 探索配置
  explore_count: 5

  # 速率控制
  rate_control:
    base_delay: 1.0
    random_range: 0.5
    backoff_factor: 1.5
    max_level: 5
    credit_recovery: 10

  # 断点续传
  checkpoint:
    enabled: true
    interval: 20
    storage: "redis"
```

## 高级用法

### 自定义恢复策略

对于特殊的网站结构，用户可以实现自定义的恢复策略。只需继承 ResumeStrategy 抽象类，实现 name 属性和 try_resume 方法即可。

```python
from autospider.checkpoint import ResumeStrategy

class CustomResumeStrategy(ResumeStrategy):
    def __init__(self, custom_param: str):
        self.custom_param = custom_param
    
    @property
    def name(self) -> str:
        return "自定义恢复策略"
    
    async def try_resume(self, page, target_page: int) -> tuple[bool, int]:
        # 自定义恢复逻辑
        await page.goto(f"/page/{target_page}")
        return True, target_page
```

### 多策略协调

ResumeCoordinator 能够自动协调多种恢复策略，按照优先级依次尝试，直到成功恢复或所有策略都失败。这种设计确保了系统在面对不同类型的网站时都能找到合适的恢复方式。

```python
from autospider.checkpoint import ResumeCoordinator

strategies = [
    URLPatternStrategy(list_url),      # 策略1：URL规律爆破
    WidgetJumpStrategy(xpath),         # 策略2：控件直达
    SmartSkipStrategy(...)             # 策略3：智能跳过（兜底）
]

coordinator = ResumeCoordinator(strategies)
success, actual_page = await coordinator.try_resume(page, target_page=100)
```

### 速率事件监听

用户可以监听速率控制器的状态变化事件，以便实时了解采集进度和速率调整情况。

```python
controller = AdaptiveRateController()

def on_rate_change(level, delay):
    print(f"速率等级变更: {level}, 当前延迟: {delay:.2f}s")

# 可以在采集循环中检查状态
for page in pages:
    try:
        await controller.before_request()
        # 执行采集...
        controller.record_success()
    except AntiCrawlerException:
        controller.apply_penalty()
```

## 最佳实践

配置 Crawler 模块时需要综合考虑目标网站的反爬策略、采集效率要求和稳定性需求。对于反爬严格的网站，建议降低基础延迟、增加退避因子、提高恢复阈值，以确保采集任务能够长期稳定运行。对于反爬较宽松的网站，可以适当提高采集速度，但也要设置合理的最大降速等级，防止突发情况导致过度降速。

断点续传功能强烈建议在长时间采集任务中启用。配置 Redis 存储可以实现多进程共享进度，适合分布式采集场景；配置内存存储则适合单进程短期任务。无论使用哪种存储方式，都应设置合理的检查点保存间隔，既保证进度不丢失，又避免过于频繁的 I/O 操作影响性能。

探索阶段的采样数量需要根据列表页的结构复杂度来调整。对于结构简单、规律明显的列表页，3-5 个样本通常就能准确推断出详情页的公共特征；对于结构复杂多变的列表页，可能需要增加采样数量，但也要注意平衡探索成本和采集效率。
