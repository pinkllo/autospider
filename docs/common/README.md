# Common 模块

Common 模块提供 AutoSpider 项目的基础设施和公共工具，包括配置管理、类型定义、浏览器操作、SoM 标注系统和存储管理。

---

## 📁 模块结构

```
common/
├── __init__.py              # 模块导出
├── config.py                # 配置管理（Pydantic 模型）
├── types.py                 # 核心数据类型定义
├── browser/                 # 浏览器操作
│   ├── __init__.py
│   ├── actions.py          # 动作执行器
│   └── session.py          # 浏览器会话管理
├── som/                    # Set-of-Mark 标注系统
│   ├── __init__.py
│   ├── api.py              # SoM Python API
│   └── inject.js           # 注入脚本
└── storage/                # 持久化存储
    ├── __init__.py
    ├── persistence.py      # 持久化基类
    └── redis_manager.py    # Redis 管理器
```

---

## 📑 函数目录

### ⚙️ 配置管理 (config.py)
- `LLMConfig` - LLM 配置
- `BrowserConfig` - 浏览器配置
- `AgentConfig` - Agent 配置
- `RedisConfig` - Redis 配置
- `URLCollectorConfig` - URL 收集器配置
- `Config` - 全局配置
- `config` - 全局配置实例

### 📦 类型定义 (types.py)
- `RunInput` - Agent 运行输入参数
- `BoundingBox` - 元素边界框
- `XPathCandidate` - XPath 候选项
- `ElementMark` - SoM 标注的元素
- `ScrollInfo` - 页面滚动状态
- `SoMSnapshot` - SoM 快照
- `ActionType` - 动作类型枚举
- `Action` - LLM 输出的动作
- `ActionResult` - 动作执行结果
- `ScriptStepType` - 脚本步骤类型
- `ScriptStep` - XPath 脚本步骤
- `XPathScript` - 完整的 XPath 脚本
- `AgentState` - Agent 状态

### 🎯 动作执行器 (actions.py)
- `ActionExecutor` - 动作执行器主类
- `execute(action, mark_id_to_xpath, step_index)` - 执行动作

### 💼 浏览器会话管理 (session.py)
- `BrowserSession` - 浏览器会话管理器
- `create_browser_session()` - 创建浏览器会话上下文管理器

### 🔧 SoM Python API (api.py)
- `inject_and_scan(page)` - 注入并扫描页面
- `capture_screenshot_with_marks(page)` - 带标注的截图
- `clear_overlay(page)` - 清除覆盖层
- `set_overlay_visibility(page, visible)` - 设置覆盖层可见性
- `get_element_by_mark_id(page, mark_id)` - 根据 mark_id 获取元素
- `build_mark_id_to_xpath_map(snapshot)` - 构建映射
- `format_marks_for_llm(snapshot, max_marks)` - 格式化标注信息

### 💾 Redis 管理器 (redis_manager.py)
- `RedisManager` - Redis 管理器主类
- `connect()` - 连接到 Redis
- `disconnect()` - 断开连接
- `save_item(item, metadata)` - 保存单个数据项
- `save_items_batch(items, metadata_list)` - 批量保存数据项
- `load_items()` - 加载所有数据项
- `mark_as_deleted(item)` - 标记为逻辑删除
- `mark_as_deleted_batch(items)` - 批量标记删除
- `is_deleted(item)` - 检查是否已删除
- `get_active_items()` - 获取活跃数据项
- `get_metadata(item)` - 获取元数据
- `get_count()` - 获取总数
- `get_active_count()` - 获取活跃数量

---

## 🚀 核心功能

### 配置管理

使用 Pydantic 的 `BaseModel` 实现类型安全的配置管理，支持环境变量覆盖。

```python
from autospider.common.config import config

# 使用全局配置
print(f"LLM 模型: {config.llm.model}")
print(f"浏览器视口: {config.browser.viewport_width}x{config.browser.viewport_height}")
print(f"Redis 启用: {config.redis.enabled}")

# 确保输出目录存在
config.ensure_dirs()
```

### 类型定义

定义了整个项目使用的核心数据类型，包括 SoM 标注、动作定义、LangGraph 状态等。

```python
from autospider.common.types import RunInput, Action, ActionType

# 创建运行输入
input_data = RunInput(
    start_url="https://example.com",
    task="点击登录按钮，输入用户名和密码",
    target_text="欢迎回来",
    max_steps=30,
    headless=True
)

# 创建动作
action = Action(
    action=ActionType.CLICK,
    mark_id=5,
    target_text="登录按钮",
    thinking="需要点击登录按钮来提交表单"
)
```

### 动作执行器

负责执行 LLM 输出的动作，并将其沉淀为可复用的 XPath 脚本。

```python
from autospider.common.browser.actions import ActionExecutor

executor = ActionExecutor(page)

# 执行动作
action = Action(action=ActionType.CLICK, mark_id=5)
result, script_step = await executor.execute(
    action,
    mark_id_to_xpath={5: ["//button[@id='login']", "//button[text()='登录']"]},
    step_index=1
)

print(f"执行成功: {result.success}")
if script_step:
    print(f"生成的脚本步骤: {script_step.model_dump_json()}")
```

### 浏览器会话管理

管理浏览器的会话状态，包括Cookie、本地存储和会话数据。

```python
from autospider.common.browser.session import create_browser_session

# 使用上下文管理器（推荐）
async with create_browser_session(
    headless=True,
    viewport_width=1920,
    viewport_height=1080
) as session:
    page = session.page
    await session.navigate("https://example.com")
    await session.wait_for_stable()

    # 执行其他操作...
    title = await page.title()
    print(f"页面标题: {title}")
```

### SoM 标注系统

提供 Set-of-Mark 标注的核心 API，为网页元素提供可视化标注和交互能力。

```python
from autospider.common.som.api import inject_and_scan, build_mark_id_to_xpath_map

# 注入并扫描页面
snapshot = await inject_and_scan(page)

print(f"当前 URL: {snapshot.url}")
print(f"页面标题: {snapshot.title}")
print(f"发现 {len(snapshot.marks)} 个可交互元素")

# 构建 mark_id 到 XPath 的映射
xpath_map = build_mark_id_to_xpath_map(snapshot)
print(f"XPath 映射: {xpath_map}")
```

### Redis 存储

提供通用的 Redis 数据管理工具，支持逻辑删除和批量操作。

```python
from autospider.common.storage.redis_manager import RedisManager

# 创建管理器
manager = RedisManager(
    host="localhost",
    port=6379,
    password=None,
    db=0,
    key_prefix="autospider:urls"
)

# 连接
await manager.connect()

# 保存数据项
await manager.save_item("https://example.com/page1")

# 批量保存
await manager.save_items_batch([
    "https://example.com/page2",
    "https://example.com/page3"
])

# 加载所有数据项
items = await manager.load_items()
print(f"已加载 {len(items)} 个数据项")

# 获取活跃数据项
active_items = await manager.get_active_items()
print(f"活跃数据项: {len(active_items)}")

# 断开连接
await manager.disconnect()
```

---

## 💡 特性说明

### 环境变量支持

所有配置项都支持通过环境变量进行覆盖：

```bash
# .env 文件
AIPING_API_KEY=your-api-key
AIPING_MODEL=gpt-4-vision
HEADLESS=true
VIEWPORT_WIDTH=1920
VIEWPORT_HEIGHT=1080
REDIS_ENABLED=true
REDIS_HOST=localhost
REDIS_PORT=6379
```

### 类型安全

使用 Pydantic 进行类型验证，确保配置和数据的正确性：

```python
from pydantic import ValidationError

try:
    config = LLMConfig(
        api_key="test-key",
        model="gpt-4",
        temperature=0.1,
        max_tokens=8192
    )
except ValidationError as e:
    print(f"配置验证失败: {e}")
```

### 异步支持

所有 I/O 操作都支持异步，提高性能：

```python
import asyncio

async def main():
    # 异步连接 Redis
    await manager.connect()

    # 异步保存数据
    await manager.save_item("https://example.com")

    # 异步加载数据
    items = await manager.load_items()

    # 异步断开连接
    await manager.disconnect()

asyncio.run(main())
```

---

## 🔧 使用示例

### 完整的配置管理流程

```python
from autospider.common.config import Config, config

# 方式 1: 使用全局配置
print(f"LLM API Key: {config.llm.api_key}")
print(f"LLM 模型: {config.llm.model}")
print(f"浏览器无头模式: {config.browser.headless}")

# 方式 2: 创建自定义配置
custom_config = Config(
    llm=LLMConfig(
        api_key="custom-key",
        model="gpt-4",
        temperature=0.2
    ),
    browser=BrowserConfig(
        headless=True,
        viewport_width=1920,
        viewport_height=1080
    )
)

# 确保输出目录存在
config.ensure_dirs()
```

### SoM 标注与动作执行

```python
from autospider.common.som.api import inject_and_scan, build_mark_id_to_xpath_map
from autospider.common.browser.actions import ActionExecutor

# 注入 SoM 系统
snapshot = await inject_and_scan(page)

# 构建 XPath 映射
xpath_map = build_mark_id_to_xpath_map(snapshot)

# 创建动作执行器
executor = ActionExecutor(page)

# 执行点击动作
action = Action(
    action=ActionType.CLICK,
    mark_id=5,
    target_text="登录按钮"
)

result, script_step = await executor.execute(
    action,
    xpath_map,
    step_index=1
)

print(f"执行结果: {result.success}")
```

### Redis 数据管理

```python
from autospider.common.storage.redis_manager import RedisManager

# 创建管理器
manager = RedisManager(key_prefix="crawler:urls")

# 连接
await manager.connect()

try:
    # 保存 URL
    await manager.save_item("https://example.com/product/1")

    # 检查是否存在
    is_deleted = await manager.is_deleted("https://example.com/product/1")
    print(f"是否已删除: {is_deleted}")

    # 标记为删除
    await manager.mark_as_deleted("https://example.com/product/1")

    # 获取活跃 URL
    active_urls = await manager.get_active_items()
    print(f"活跃 URL 数量: {len(active_urls)}")

    # 获取元数据
    metadata = await manager.get_metadata("https://example.com/product/1")
    print(f"元数据: {metadata}")

finally:
    # 断开连接
    await manager.disconnect()
```

---

## 📝 最佳实践

### 配置管理

1. **环境变量优先**：使用环境变量覆盖默认配置
2. **类型验证**：利用 Pydantic 的类型验证功能
3. **目录管理**：使用 `ensure_dirs()` 确保输出目录存在
4. **配置分离**：不同环境使用不同的配置文件

### 类型定义

1. **类型注解**：始终使用类型注解
2. **默认值**：为可选字段提供合理的默认值
3. **验证逻辑**：使用 Pydantic 的验证器
4. **文档字符串**：为每个类型添加详细的文档

### 动作执行

1. **错误处理**：捕获并处理执行错误
2. **脚本沉淀**：将成功的动作沉淀为脚本步骤
3. **XPath 优先级**：使用多个 XPath 候选提高稳定性
4. **超时控制**：为每个动作设置合理的超时时间

### SoM 标注

1. **元素过滤**：只标注真正可交互的元素
2. **XPath 生成**：生成稳定的 XPath 候选
3. **可见性检查**：确保元素真正可见
4. **坐标归一化**：使用归一化坐标便于 LLM 理解

### Redis 存储

1. **连接管理**：使用上下文管理器确保连接正确关闭
2. **批量操作**：使用批量操作提高性能
3. **逻辑删除**：使用逻辑删除保留历史记录
4. **命名空间**：使用 key_prefix 避免数据冲突

---

## 🔍 故障排除

### 常见问题

1. **配置加载失败**
   - 检查 .env 文件是否存在
   - 验证环境变量格式
   - 确认默认值是否合理

2. **动作执行失败**
   - 检查 mark_id 是否正确
   - 验证 XPath 候选是否有效
   - 确认元素是否可见和可交互

3. **SoM 注入失败**
   - 检查页面是否完全加载
   - 验证注入脚本语法
   - 确认浏览器支持情况

4. **Redis 连接失败**
   - 检查 Redis 服务是否运行
   - 验证连接参数
   - 确认网络连通性

### 调试技巧

```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 检查配置
print(config.model_dump_json(indent=2))

# 验证动作
print(action.model_dump_json(indent=2))

# 检查 SoM 快照
print(f"标注数量: {len(snapshot.marks)}")
for mark in snapshot.marks:
    print(f"[{mark.mark_id}] {mark.tag}: {mark.text}")

# 测试 Redis 连接
await manager.connect()
print(f"连接成功: {manager.client is not None}")
```

---

*最后更新: 2026-01-08*
