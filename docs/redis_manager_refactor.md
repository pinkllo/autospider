# RedisManager 模块重构说明

## 概述

`RedisManager` 已重构为一个**完全独立、可复用的通用 Redis 管理工具**，可用于任何 Python 项目。

## 主要改进

### 1. 移除项目依赖
- ✅ **默认 key_prefix**: 从 `"autospider:urls"` 改为通用的 `"data"`
- ✅ **日志系统**: 使用 Python 标准 `logging` 模块替代 `print()`
- ✅ **日志格式**: 移除硬编码的 `[Redis]` 前缀，由调用方决定

### 2. API 通用化
原有 API（面向 URL 场景）：
```python
await redis_manager.load_urls()       # 加载 URL
await redis_manager.save_url(url)     # 保存单个 URL
await redis_manager.save_urls_batch(urls)  # 批量保存 URL
await redis_manager.get_active_urls() # 获取活跃 URL
```

新 API（通用数据项）：
```python
await redis_manager.load_items()       # 加载所有数据项
await redis_manager.save_item(item, metadata)  # 保存单个数据项（支持元数据）
await redis_manager.save_items_batch(items, metadata_list)  # 批量保存
await redis_manager.get_active_items() # 获取活跃数据项
await redis_manager.get_metadata(item) # 【新增】获取数据项元数据
```

### 3. 增强的功能

#### 自定义 Logger
```python
import logging

# 创建自定义 logger
logger = logging.getLogger("my_app.redis")
logger.setLevel(logging.INFO)

redis_manager = RedisManager(
    host="localhost",
    port=6379,
    key_prefix="myapp:cache",
    logger=logger  # 传入自定义 logger
)
```

#### 元数据支持
```python
# 保存数据项时附加元数据
await redis_manager.save_item(
    "https://example.com/page1",
    metadata={
        "collected_at": "2026-01-07",
        "priority": "high",
        "source": "crawler_1"
    }
)

# 获取元数据
metadata = await redis_manager.get_metadata("https://example.com/page1")
# 返回: {"item": "...", "deleted": "false", "collected_at": "...", ...}
```

## 使用示例

### 在 autospider 项目中使用

```python
import logging
from redis_manager import RedisManager

# 创建带项目前缀的 logger
redis_logger = logging.getLogger("autospider.redis")
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("[Redis] %(message)s"))
redis_logger.addHandler(handler)
redis_logger.setLevel(logging.INFO)

# 初始化 RedisManager
redis_manager = RedisManager(
    host=config.redis.host,
    port=config.redis.port,
    password=config.redis.password,
    db=config.redis.db,
    key_prefix=config.redis.key_prefix,  # e.g., "autospider:urls"
    logger=redis_logger,
)

# 连接并使用
await redis_manager.connect()
urls = await redis_manager.load_items()  # 加载历史 URLs
await redis_manager.save_item(url)       # 保存新 URL
```

### 在其他项目中使用

```python
from redis_manager import RedisManager

# 作为缓存管理器
cache_manager = RedisManager(
    key_prefix="myapp:cache",
    logger=my_logger,
)

await cache_manager.connect()
await cache_manager.save_item("user:123", {"name": "Alice", "age": "30"})

# 作为任务队列状态追踪
task_manager = RedisManager(
    key_prefix="tasks",
    db=1,  # 使用不同的数据库
)

await task_manager.save_item("task_001", {"status": "pending"})
await task_manager.mark_as_deleted("task_001")  # 标记为已完成
```

## 兼容性

项目现有代码已更新以适配新 API：
- `url_collector.py` 已修改为使用 `load_items()` 和 `save_item()`
- 添加了自定义 logger 以保持 `[Redis]` 日志前缀
- 功能完全兼容，无需修改配置文件

## 核心特性

### 逻辑删除（软删除）
```python
# 标记为删除（数据仍保留）
await redis_manager.mark_as_deleted("item_id")

# 检查是否删除
is_deleted = await redis_manager.is_deleted("item_id")

# 只获取未删除的项
active_items = await redis_manager.get_active_items()
```

### 批量操作
```python
# 批量保存
items = ["url1", "url2", "url3"]
metadata_list = [
    {"priority": "high"},
    {"priority": "medium"},
    {"priority": "low"}
]
await redis_manager.save_items_batch(items, metadata_list)

# 批量删除
await redis_manager.mark_as_deleted_batch(["url1", "url2"])
```

### 统计信息
```python
# 总数（包括已删除）
total = await redis_manager.get_count()

# 活跃数（未删除）
active = await redis_manager.get_active_count()
```

## 总结

重构后的 `RedisManager`：
- ✅ **完全独立**：无任何项目特定依赖
- ✅ **高度抽象**：通用的数据项管理，而非特定于 URL
- ✅ **可配置**：支持自定义 logger、key_prefix、数据库等
- ✅ **功能丰富**：支持元数据、逻辑删除、批量操作
- ✅ **向后兼容**：现有项目代码已适配，无需修改配置

可以直接将此模块复用到其他任何需要 Redis 数据管理的 Python 项目中！
