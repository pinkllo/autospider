# Checkpoint 子模块

Checkpoint 子模块实现断点续传系统，提供自适应速率控制和恢复策略，确保长时间运行的爬取任务能够从中断点恢复。

---

## 📁 模块结构

```
src/autospider/crawler/checkpoint/
├── __init__.py              # 模块导出
├── rate_controller.py       # 自适应速率控制器
└── resume_strategy.py       # 断点恢复策略
```

---

## 📑 函数目录

### ⚡ 自适应速率控制器 (rate_controller.py)
- `AdaptiveRateController` - 速率控制器主类
- `get_delay()` - 获取当前延迟时间
- `apply_penalty()` - 应用惩罚（遇到反爬时）
- `record_success()` - 记录成功请求
- `set_level(level)` - 设置降速等级
- `reset()` - 重置控制器状态

### 🔄 断点恢复策略 (resume_strategy.py)
- `ResumeStrategy` - 恢复策略基类
- `URLPatternStrategy` - URL规律爆破策略
- `WidgetJumpStrategy` - 控件直达策略
- `SmartSkipStrategy` - 智能跳过策略
- `ResumeCoordinator` - 恢复策略协调器

---

## 🚀 核心功能

### 自适应速率控制

AdaptiveRateController 实现智能速率控制算法，根据网站反爬情况自动调整请求频率。

```python
from autospider.crawler.checkpoint.rate_controller import AdaptiveRateController

# 创建速率控制器
controller = AdaptiveRateController(
    base_delay=1.0,          # 基础延迟1秒
    backoff_factor=1.5,      # 退避因子1.5
    max_level=5,             # 最大降速等级5
    credit_recovery_pages=10, # 每10个成功请求恢复一级
    initial_level=0          # 初始等级0
)

# 获取当前延迟时间
delay = controller.get_delay()
print(f"当前延迟: {delay}秒")

# 模拟请求过程
for page_num in range(1, 21):
    # 获取延迟并等待
    current_delay = controller.get_delay()
    print(f"第{page_num}页 - 延迟: {current_delay:.2f}秒")

    # 模拟请求（假设第5页遇到反爬）
    if page_num == 5:
        print("遇到反爬机制，应用惩罚")
        controller.apply_penalty()
    else:
        # 记录成功请求
        controller.record_success()

    # 等待延迟时间
    await asyncio.sleep(current_delay)

print(f"最终降速等级: {controller.current_level}")
```

### 断点恢复策略

提供多种恢复策略，根据网站特点选择最合适的恢复方式。

```python
from autospider.crawler.checkpoint.resume_strategy import (
    ResumeCoordinator,
    URLPatternStrategy,
    WidgetJumpStrategy,
    SmartSkipStrategy
)

# 创建各种恢复策略
url_strategy = URLPatternStrategy(
    list_url="https://example.com/products?page=1"
)

widget_strategy = WidgetJumpStrategy(
    jump_widget_xpath={
        "input": "input.page-input",
        "button": "button.go-btn"
    }
)

smart_strategy = SmartSkipStrategy(
    list_url="https://example.com/products",
    item_xpath="//div[@class='product-item']",
    nav_steps=[
        {"action": "scroll", "direction": "down", "times": 2},
        {"action": "click", "selector": "button.next-page"}
    ]
)

# 创建协调器
coordinator = ResumeCoordinator([url_strategy, widget_strategy, smart_strategy])

# 尝试从第50页恢复
current_page = 10
target_page = 50

result = await coordinator.try_resume(current_page, target_page)

if result.success:
    print(f"成功恢复到第{result.resumed_page}页")
    print(f"使用的策略: {result.strategy_used}")
    print(f"跳过的页数: {result.pages_skipped}")
else:
    print("恢复失败，需要手动处理")
    print(f"失败原因: {result.error_message}")
```

---

## 💡 特性说明

### 速率控制算法

基于指数退避策略的智能速率控制：

```python
# 延迟计算公式
current_delay = base_delay * (backoff_factor ^ current_level)

# 惩罚机制
- 每次触发惩罚，current_level 增加1
- 延迟时间按指数增长
- 避免短时间内频繁触发惩罚

# 恢复机制
- 每成功处理 credit_recovery_pages 个页面，current_level 减少1
- 逐步恢复正常速率
- 防止快速波动
```

### 恢复策略选择

系统自动选择最适合的恢复策略：

1. **URLPatternStrategy**：适用于URL包含页码参数的网站
   - 直接构造目标页URL
   - 快速跳转，效率最高
   - 需要URL规律明显

2. **WidgetJumpStrategy**：适用于使用页码输入控件的网站
   - 模拟输入页码并点击确定
   - 适用于现代Web应用
   - 需要控件定位准确

3. **SmartSkipStrategy**：兜底方案，通用性最强
   - 从第一页开始快速检测
   - 检测到新数据时回退一页
   - 确保数据完整性

### 状态持久化

支持控制器状态的保存和恢复：

```python
# 保存当前状态
state = controller.get_state()
await storage.save_data("rate_controller_state", state)

# 恢复状态
saved_state = await storage.load_data("rate_controller_state")
if saved_state:
    controller.restore_state(saved_state)
    print("速率控制器状态已恢复")
```

---

## 🔧 使用示例

### 完整的爬取任务管理

```python
import asyncio
from autospider.crawler.checkpoint.rate_controller import AdaptiveRateController
from autospider.crawler.checkpoint.resume_strategy import ResumeCoordinator
from autospider.common.storage.redis_manager import RedisManager

class CrawlTaskManager:
    """爬取任务管理器"""

    def __init__(self, task_id, list_url, storage_manager):
        self.task_id = task_id
        self.list_url = list_url
        self.storage = storage_manager

        # 创建速率控制器
        self.rate_controller = AdaptiveRateController(
            base_delay=1.0,
            backoff_factor=1.5,
            max_level=5,
            credit_recovery_pages=10
        )

        # 创建恢复策略协调器
        self.resume_coordinator = ResumeCoordinator.create_default(list_url)

    async def load_progress(self):
        """加载任务进度"""
        progress_key = f"task:{self.task_id}:progress"
        progress = await self.storage.get_metadata(progress_key)

        if progress:
            # 恢复速率控制器状态
            if 'rate_controller_state' in progress:
                self.rate_controller.restore_state(progress['rate_controller_state'])

            return progress['current_page'], progress['collected_urls']

        return 1, []  # 从头开始

    async def save_progress(self, current_page, collected_urls):
        """保存任务进度"""
        progress_key = f"task:{self.task_id}:progress"

        progress_data = {
            'current_page': current_page,
            'collected_urls': collected_urls,
            'rate_controller_state': self.rate_controller.get_state(),
            'last_saved': '2026-01-08T10:00:00Z'
        }

        await self.storage.save_item(progress_key, progress_data)

    async def crawl_page(self, page_num):
        """爬取单个页面"""
        # 获取当前延迟
        delay = self.rate_controller.get_delay()
        print(f"爬取第{page_num}页，延迟: {delay:.2f}秒")

        # 等待延迟时间
        await asyncio.sleep(delay)

        try:
            # 模拟页面爬取（这里应该是实际的爬取逻辑）
            if page_num % 7 == 0:  # 模拟偶尔遇到反爬
                print(f"第{page_num}页遇到反爬机制")
                self.rate_controller.apply_penalty()
                raise Exception("Anti-crawler detected")

            # 模拟成功爬取
            urls = [f"https://example.com/product/{page_num * 10 + i}"
                   for i in range(10)]

            self.rate_controller.record_success()
            return urls

        except Exception as e:
            print(f"爬取第{page_num}页失败: {e}")
            return []

    async def resume_to_page(self, current_page, target_page):
        """恢复到指定页面"""
        print(f"尝试从第{current_page}页恢复到第{target_page}页")

        result = await self.resume_coordinator.try_resume(current_page, target_page)

        if result.success:
            print(f"成功恢复到第{result.resumed_page}页")
            return result.resumed_page
        else:
            print("恢复失败，从头开始")
            return 1

    async def run(self, max_pages=100):
        """运行爬取任务"""
        # 加载进度
        current_page, collected_urls = await self.load_progress()

        print(f"开始爬取，当前进度: 第{current_page}页")

        while current_page <= max_pages:
            # 爬取当前页面
            new_urls = await self.crawl_page(current_page)
            collected_urls.extend(new_urls)

            # 每5页保存一次进度
            if current_page % 5 == 0:
                await self.save_progress(current_page, collected_urls)
                print(f"进度已保存: 第{current_page}页，URL数量: {len(collected_urls)}")

            current_page += 1

        # 任务完成，清理进度数据
        await self.storage.delete(f"task:{self.task_id}:progress")
        print(f"任务完成! 共收集 {len(collected_urls)} 个URL")

        return collected_urls

# 使用示例
async def main():
    # 创建存储管理器
    storage = RedisManager(key_prefix="crawler:")
    await storage.connect()

    try:
        # 创建任务管理器
        task_manager = CrawlTaskManager(
            task_id="demo_task",
            list_url="https://example.com/products?page=1",
            storage_manager=storage
        )

        # 运行爬取任务
        urls = await task_manager.run(max_pages=20)

        print(f"最终收集的URL数量: {len(urls)}")

    finally:
        await storage.disconnect()

asyncio.run(main())
```

---

## 📝 最佳实践

### 速率控制配置

1. **基础延迟**：根据目标网站响应时间设置
2. **退避因子**：1.3-2.0之间，避免过于激进
3. **最大等级**：3-5级，避免延迟过长
4. **恢复阈值**：8-15个成功请求恢复一级

### 恢复策略选择

1. **优先URL模式**：URL规律明显时效率最高
2. **次选控件跳转**：现代Web应用适用
3. **兜底智能跳过**：通用性强但效率较低
4. **混合策略**：根据实际情况组合使用

### 状态管理

1. **定期保存**：每爬取一定数量页面后保存状态
2. **异常处理**：捕获异常并保存当前状态
3. **状态验证**：恢复时验证状态完整性
4. **清理机制**：任务完成后清理状态数据

---

## 🔍 故障排除

### 常见问题

1. **速率控制过于保守**
   - 调整基础延迟和退避因子
   - 增加恢复阈值
   - 考虑网站的实际反爬强度

2. **恢复策略失败**
   - 检查URL模式是否正确
   - 验证控件定位准确性
   - 考虑使用兜底策略

3. **状态恢复异常**
   - 检查状态数据完整性
   - 验证序列化/反序列化过程
   - 确认存储后端正常工作

### 调试技巧

```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 监控速率控制器状态
print(f"当前等级: {controller.current_level}")
print(f"成功计数: {controller.success_count}")
print(f"信用值: {controller.credit}")

# 测试恢复策略
for strategy in coordinator.strategies:
    print(f"策略 {strategy.__class__.__name__}: {strategy.description}")

# 性能监控
import time
start_time = time.time()
# 执行操作
end_time = time.time()
print(f"操作耗时: {end_time - start_time:.3f}秒")
```

---

*最后更新: 2026-01-08*
