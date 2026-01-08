# base_collector.py - 收集器基类

base_collector.py 模块提供 URL 收集器的基类，抽取 URLCollector 和 BatchCollector 的公共逻辑，减少代码重复，提高可维护性。

---

## 📁 文件路径

```
src/autospider/crawler/base_collector.py
```

---

## 📑 函数目录

### 🚀 核心类
- `BaseCollector` - URL 收集器基类（抽象类）

### 🔧 主要方法
- `run()` - 运行收集流程（抽象方法）
- `_initialize_handlers()` - 初始化各个处理器
- `_load_previous_urls()` - 从 Redis 加载历史 URL
- `_resume_to_target_page()` - 使用三阶段策略恢复到目标页
- `_collect_phase_with_xpath()` - 收集阶段：使用公共 XPath
- `_collect_phase_with_llm()` - 收集阶段：使用 LLM
- `_save_progress()` - 保存收集进度

### 🔍 内部方法
- `_is_progress_compatible()` - 检查进度是否与当前任务匹配
- `_extract_urls_with_xpath()` - 使用 XPath 提取当前页的 URL
- `_collect_page_with_llm()` - 使用 LLM 收集单页的 URL
- `_create_result()` - 创建收集结果

---

## 🚀 核心功能

### BaseCollector

URL 收集器基类，提供公共的收集逻辑。

```python
from autospider.crawler.base_collector import BaseCollector

# BaseCollector 是抽象类，需要子类实现
class MyCollector(BaseCollector):
    async def run(self) -> URLCollectorResult:
        # 实现收集流程
        return self._create_result()

# 创建收集器
collector = MyCollector(
    page=page,
    list_url="https://example.com/list",
    task_description="收集详情页链接",
    output_dir="output"
)

# 运行收集流程
result = await collector.run()
```

### 公共功能

BaseCollector 提供以下公共功能：

1. **速率控制**
```python
# 速率控制器自动初始化
self.rate_controller = AdaptiveRateController()

# 获取当前延迟
delay = self.rate_controller.get_delay()

# 记录成功
self.rate_controller.record_success()

# 应用惩罚
self.rate_controller.apply_penalty()
```

2. **断点续爬**
```python
# 加载历史 URL
await self._load_previous_urls()

# 恢复到目标页
actual_page = await self._resume_to_target_page(target_page_num)

# 保存进度
self._save_progress()
```

3. **Redis 持久化**
```python
# Redis 管理器自动初始化（如果启用）
self.redis_manager: RedisManager | None = None

# 保存 URL
if self.redis_manager:
    await self.redis_manager.save_item(url)

# 加载 URL
if self.redis_manager:
    urls = await self.redis_manager.load_items()
```

4. **XPath/LLM 收集**
```python
# 使用 XPath 收集
await self._collect_phase_with_xpath()

# 使用 LLM 收集
await self._collect_phase_with_llm()
```

5. **分页处理**
```python
# 分页处理器自动初始化
self.pagination_handler = PaginationHandler(...)

# 点击下一页
page_turned = await self.pagination_handler.find_and_click_next_page()
```

---

## 💡 特性说明

### 抽象基类设计

BaseCollector 使用抽象基类设计，强制子类实现 `run()` 方法：

```python
from abc import ABC, abstractmethod

class BaseCollector(ABC):
    @abstractmethod
    async def run(self) -> URLCollectorResult:
        """运行收集流程（子类实现）"""
        pass
```

### 处理器延迟初始化

处理器在 `_initialize_handlers()` 方法中延迟初始化：

```python
def _initialize_handlers(self) -> None:
    """初始化各个处理器
    
    子类可覆盖此方法添加额外的初始化逻辑。
    """
    self.url_extractor = URLExtractor(self.page, self.list_url)
    self.navigation_handler = NavigationHandler(...)
    self.pagination_handler = PaginationHandler(...)
```

### 配置驱动的 Redis

Redis 管理器根据配置自动初始化：

```python
def _init_redis_manager(self) -> None:
    """初始化 Redis 管理器"""
    if not config.redis.enabled:
        return
    
    try:
        from ..common.storage.redis_manager import RedisManager
        self.redis_manager = RedisManager(...)
    except ImportError:
        logger.warning("Redis 依赖未安装")
```

### 进度兼容性检查

在恢复进度前检查进度是否与当前任务匹配：

```python
def _is_progress_compatible(self, progress: CollectionProgress | None) -> bool:
    """检查进度是否与当前任务匹配"""
    if not progress:
        return False
    if progress.list_url and progress.list_url != self.list_url:
        return False
    if progress.task_description and progress.task_description != self.task_description:
        return False
    return True
```

---

## 🔧 使用示例

### 创建自定义收集器

```python
from autospider.crawler.base_collector import BaseCollector
from autospider.extractor.collector import URLCollectorResult

class CustomCollector(BaseCollector):
    """自定义收集器"""
    
    def __init__(self, page, list_url, task_description, output_dir="output"):
        super().__init__(page, list_url, task_description, output_dir)
        
        # 添加自定义初始化
        self.custom_config = {}
    
    def _initialize_handlers(self) -> None:
        """覆盖初始化方法"""
        super()._initialize_handlers()
        
        # 添加自定义处理器
        pass
    
    async def run(self) -> URLCollectorResult:
        """实现收集流程"""
        # 1. 加载历史 URL
        await self._load_previous_urls()
        
        # 2. 导航到列表页
        await self.page.goto(self.list_url, wait_until="domcontentloaded")
        
        # 3. 初始化处理器
        self._initialize_handlers()
        
        # 4. 收集 URL
        if self.common_detail_xpath:
            await self._collect_phase_with_xpath()
        else:
            await self._collect_phase_with_llm()
        
        # 5. 返回结果
        return self._create_result()

# 使用自定义收集器
collector = CustomCollector(
    page=page,
    list_url="https://example.com/list",
    task_description="收集详情页链接",
    output_dir="output"
)

result = await collector.run()
```

### 覆盖初始化方法

```python
class EnhancedCollector(BaseCollector):
    """增强型收集器"""
    
    def _initialize_handlers(self) -> None:
        """覆盖初始化方法，添加额外逻辑"""
        # 调用父类初始化
        super()._initialize_handlers()
        
        # 添加自定义初始化
        self.custom_handler = CustomHandler(...)
        
        # 配置处理器
        self.pagination_handler.custom_config = {...}
```

### 自定义进度保存

```python
class CustomCollector(BaseCollector):
    """自定义进度保存"""
    
    def _save_progress(self) -> None:
        """覆盖进度保存方法"""
        # 调用父类保存
        super()._save_progress()
        
        # 添加自定义保存逻辑
        custom_progress = {
            "custom_field": self.custom_value,
            "timestamp": datetime.now().isoformat()
        }
        
        custom_file = self.output_dir / "custom_progress.json"
        custom_file.write_text(json.dumps(custom_progress))
```

---

## 📝 最佳实践

### 继承 BaseCollector

1. **实现抽象方法**：必须实现 `run()` 方法
2. **调用父类初始化**：在 `__init__` 中调用 `super().__init__()`
3. **覆盖初始化方法**：在 `_initialize_handlers()` 中添加自定义逻辑
4. **使用公共功能**：充分利用基类提供的速率控制、断点续爬等功能

### 处理器管理

1. **延迟初始化**：在 `_initialize_handlers()` 中初始化处理器
2. **检查 None**：使用处理器前检查是否为 None
3. **配置处理器**：根据需要配置处理器的参数

### 进度管理

1. **定期保存**：每页收集后保存进度
2. **兼容性检查**：恢复进度前检查兼容性
3. **状态恢复**：恢复速率控制器等状态

### 错误处理

1. **捕获异常**：妥善处理各种异常情况
2. **应用惩罚**：遭遇反爬时应用速率惩罚
3. **记录日志**：详细记录操作日志

---

## 🔍 故障排除

### 常见问题

1. **子类未实现 run() 方法**
   - 确保子类实现了 `run()` 方法
   - 检查方法签名是否正确

2. **处理器未初始化**
   - 确保调用了 `_initialize_handlers()` 方法
   - 检查处理器是否为 None

3. **Redis 连接失败**
   - 检查 Redis 配置是否正确
   - 确认 Redis 服务是否运行
   - 验证网络连接是否正常

4. **进度恢复失败**
   - 检查进度文件是否存在
   - 验证进度是否与当前任务匹配
   - 确认配置文件是否有效

### 调试技巧

```python
# 检查处理器状态
print(f"URL Extractor: {self.url_extractor}")
print(f"Navigation Handler: {self.navigation_handler}")
print(f"Pagination Handler: {self.pagination_handler}")

# 检查收集状态
print(f"已收集 URL: {len(self.collected_urls)}")
print(f"当前页: {self.pagination_handler.current_page_num}")
print(f"降速等级: {self.rate_controller.current_level}")

# 检查 Redis 状态
if self.redis_manager:
    print(f"Redis 已连接")
else:
    print(f"Redis 未启用")
```

---

## 📚 方法参考

### BaseCollector 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `run()` | 无 | URLCollectorResult | 运行收集流程（抽象方法） |
| `_initialize_handlers()` | 无 | None | 初始化各个处理器 |
| `_load_previous_urls()` | 无 | None | 从 Redis 加载历史 URL |
| `_resume_to_target_page()` | target_page_num, jump_widget_xpath, pagination_xpath | int | 使用三阶段策略恢复到目标页 |
| `_collect_phase_with_xpath()` | 无 | None | 收集阶段：使用公共 XPath |
| `_collect_phase_with_llm()` | 无 | None | 收集阶段：使用 LLM |
| `_save_progress()` | 无 | None | 保存收集进度 |
| `_is_progress_compatible()` | progress | bool | 检查进度是否与当前任务匹配 |
| `_extract_urls_with_xpath()` | 无 | bool | 使用 XPath 提取当前页的 URL |
| `_collect_page_with_llm()` | max_scrolls, no_new_threshold | bool | 使用 LLM 收集单页的 URL |
| `_create_result()` | 无 | URLCollectorResult | 创建收集结果 |

---

*最后更新: 2026-01-08*
