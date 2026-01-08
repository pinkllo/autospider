# Storage 子模块

Storage 子模块提供数据持久化存储功能，包括 Redis 数据管理和通用持久化接口，支持断点续传和数据缓存。

---

## 📁 模块结构

```
src/autospider/common/storage/
├── __init__.py              # 模块导出
├── persistence.py           # 持久化基类
└── redis_manager.py         # Redis 管理器
```

---

## 📑 函数目录

### 💾 持久化基类 (persistence.py)
- `PersistenceBase` - 持久化基类
- `save_data(key, data)` - 保存数据
- `load_data(key)` - 加载数据
- `delete_data(key)` - 删除数据
- `exists(key)` - 检查数据是否存在

### 🔴 Redis 管理器 (redis_manager.py)
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

### 持久化基类

PersistenceBase 类定义了统一的持久化接口，支持多种存储后端的实现。

```python
from autospider.common.storage.persistence import PersistenceBase

# 创建持久化实例（具体实现由子类提供）
storage = PersistenceBase()

# 保存数据
await storage.save_data("task_progress", {
    "current_page": 5,
    "collected_urls": ["url1", "url2", "url3"],
    "last_updated": "2026-01-08T10:00:00Z"
})

# 加载数据
data = await storage.load_data("task_progress")
if data:
    print(f"当前页码: {data['current_page']}")
    print(f"已收集URL数量: {len(data['collected_urls'])}")

# 检查数据是否存在
if await storage.exists("task_progress"):
    print("任务进度数据存在")

# 删除数据
await storage.delete_data("task_progress")
```

### Redis 数据管理

RedisManager 类提供 Redis 数据库的完整操作接口，支持连接管理、数据存储和查询。

```python
from autospider.common.storage.redis_manager import RedisManager

# 创建 Redis 管理器
redis_manager = RedisManager(
    host="localhost",
    port=6379,
    password=None,
    db=0,
    key_prefix="autospider:"
)

# 连接到 Redis
await redis_manager.connect()

try:
    # 存储任务进度
    await redis_manager.save_item("https://example.com/page1")

    # 批量存储
    await redis_manager.save_items_batch([
        "https://example.com/page2",
        "https://example.com/page3"
    ])

    # 加载所有数据项
    items = await redis_manager.load_items()
    print(f"已加载 {len(items)} 个数据项")

    # 获取活跃数据项
    active_items = await redis_manager.get_active_items()
    print(f"活跃数据项: {len(active_items)}")

    # 标记为删除
    await redis_manager.mark_as_deleted("https://example.com/page1")

    # 获取元数据
    metadata = await redis_manager.get_metadata("https://example.com/page1")
    print(f"元数据: {metadata}")

finally:
    # 断开连接
    await redis_manager.disconnect()
```

---

## 💡 特性说明

### 数据序列化

支持多种数据格式的序列化和反序列化：

```python
# 存储不同类型的数据
await redis_manager.save_item("string_data", "简单字符串")
await redis_manager.save_item("number_data", "42")
await redis_manager.save_item("list_data", [1, 2, 3, 4, 5])
await redis_manager.save_item("dict_data", {"key": "value", "number": 123})
await redis_manager.save_item("complex_data", {
    "nested": {"deep": "value"},
    "list": ["a", "b", "c"],
    "timestamp": "2026-01-08T10:00:00Z"
})

# 自动反序列化
string_val = await redis_manager.load_items()  # 返回 set[str]
```

### 键命名空间

使用键前缀实现命名空间隔离，避免不同任务间的数据冲突：

```python
# 不同任务的键命名空间
task1_manager = RedisManager(key_prefix="autospider:task1:")
task2_manager = RedisManager(key_prefix="autospider:task2:")

# 存储到不同的命名空间
await task1_manager.save_item("progress", {"page": 1})
await task2_manager.save_item("progress", {"page": 5})

# 获取各自的数据
task1_items = await task1_manager.load_items()
task2_items = await task2_manager.load_items()

print(f"Task 1: {len(task1_items)} 个数据项")
print(f"Task 2: {len(task2_items)} 个数据项")
```

### 逻辑删除

支持逻辑删除功能，适用于需要保留删除记录的场景：

```python
# 保存数据项
await redis_manager.save_item("https://example.com/page1")

# 标记为逻辑删除（不真正删除数据）
await redis_manager.mark_as_deleted("https://example.com/page1")

# 检查是否已删除
is_deleted = await redis_manager.is_deleted("https://example.com/page1")
print(f"是否已删除: {is_deleted}")

# 获取活跃数据项（不包括已删除的）
active_items = await redis_manager.get_active_items()
print(f"活跃数据项: {len(active_items)}")

# 获取所有数据项（包括已删除的）
all_items = await redis_manager.load_items()
print(f"所有数据项: {len(all_items)}")
```

### 批量操作

支持批量操作提高性能：

```python
# 批量保存
urls = [
    "https://example.com/page1",
    "https://example.com/page2",
    "https://example.com/page3",
    "https://example.com/page4",
    "https://example.com/page5"
]

await redis_manager.save_items_batch(urls)
print(f"批量保存了 {len(urls)} 个数据项")

# 批量标记删除
await redis_manager.mark_as_deleted_batch(urls[:3])
print(f"批量标记删除了 3 个数据项")

# 获取活跃数量
active_count = await redis_manager.get_active_count()
print(f"活跃数据项: {active_count}")
```

---

## 🔧 使用示例

### 断点续传实现

```python
import asyncio
from autospider.common.storage.redis_manager import RedisManager

class ResumeManager:
    """断点续传管理器"""

    def __init__(self, redis_manager, task_id):
        self.redis = redis_manager
        self.task_id = task_id
        self.progress_key = f"task:{task_id}:progress"
        self.urls_key = f"task:{task_id}:urls"

    async def save_progress(self, current_page, collected_urls):
        """保存任务进度"""
        progress_data = {
            "current_page": current_page,
            "collected_urls": collected_urls,
            "last_saved": "2026-01-08T10:00:00Z",
            "total_collected": len(collected_urls)
        }

        # 保存进度数据
        await self.redis.save_item(self.progress_key, progress_data)

        # 批量保存 URL
        if collected_urls:
            await self.redis.save_items_batch(collected_urls)

        print(f"进度已保存: 页码 {current_page}, URL数量 {len(collected_urls)}")

    async def load_progress(self):
        """加载任务进度"""
        progress = await self.redis.get_metadata(self.progress_key)
        urls = await self.redis.get_active_items()

        if progress:
            print(f"从断点恢复: 页码 {progress.get('current_page', 1)}")
            return progress.get('current_page', 1), list(urls)
        else:
            print("无历史进度，从头开始")
            return 1, []

    async def cleanup(self):
        """清理任务数据"""
        await self.redis.mark_as_deleted(self.progress_key)
        print("任务数据已清理")

# 使用示例
async def main():
    redis_manager = RedisManager(key_prefix="crawler:")
    await redis_manager.connect()

    try:
        resume_manager = ResumeManager(redis_manager, "task_123")

        # 尝试加载历史进度
        start_page, existing_urls = await resume_manager.load_progress()

        # 模拟爬取过程
        current_page = start_page
        collected_urls = existing_urls.copy()

        while current_page <= 10:
            # 模拟收集URL
            new_urls = [f"https://example.com/product/{current_page * 10 + i}"
                       for i in range(10)]
            collected_urls.extend(new_urls)

            # 每页保存进度
            await resume_manager.save_progress(current_page, collected_urls)

            current_page += 1

            # 模拟意外中断
            if current_page == 5:
                print("模拟意外中断...")
                break

        print(f"任务完成，共收集 {len(collected_urls)} 个URL")

    finally:
        # 清理数据
        await resume_manager.cleanup()
        await redis_manager.disconnect()

asyncio.run(main())
```

### 数据缓存系统

```python
import asyncio
import time
from autospider.common.storage.redis_manager import RedisManager

class CacheManager:
    """数据缓存管理器"""

    def __init__(self, redis_manager, default_ttl=300):
        self.redis = redis_manager
        self.default_ttl = default_ttl

    async def get_with_cache(self, key, fetch_func, ttl=None):
        """带缓存的获取数据"""

        # 尝试从缓存获取
        metadata = await self.redis.get_metadata(key)
        if metadata and not await self.redis.is_deleted(key):
            print(f"缓存命中: {key}")
            return metadata.get("data")

        # 缓存未命中，执行获取函数
        print(f"缓存未命中: {key}, 重新获取...")
        fresh_data = await fetch_func()

        # 存储到缓存
        cache_ttl = ttl if ttl is not None else self.default_ttl
        await self.redis.save_item(key, {"data": fresh_data, "timestamp": time.time()})

        return fresh_data

    async def invalidate_cache(self, key_pattern):
        """使缓存失效"""
        # 这里需要实现模式匹配删除
        print(f"缓存失效: {key_pattern}")

# 使用示例
async def fetch_user_data(user_id):
    """模拟获取用户数据（耗时操作）"""
    print(f"正在获取用户 {user_id} 的数据...")
    await asyncio.sleep(1)
    return {
        "user_id": user_id,
        "name": f"用户{user_id}",
        "email": f"user{user_id}@example.com",
        "fetched_at": time.time()
    }

async def main():
    redis_manager = RedisManager(key_prefix="cache:")
    await redis_manager.connect()

    cache_manager = CacheManager(redis_manager, default_ttl=60)

    # 第一次获取（缓存未命中）
    user1 = await cache_manager.get_with_cache(
        "user:123",
        lambda: fetch_user_data(123),
        ttl=300
    )
    print(f"用户数据: {user1}")

    # 第二次获取（缓存命中）
    user1_cached = await cache_manager.get_with_cache(
        "user:123",
        lambda: fetch_user_data(123)
    )
    print(f"用户数据（缓存）: {user1_cached}")

    await redis_manager.disconnect()

asyncio.run(main())
```

---

## 📝 最佳实践

### 数据设计

1. **结构化存储**：使用 JSON 格式存储复杂数据
2. **键命名规范**：使用清晰的命名空间和键命名
3. **数据版本控制**：为重要数据添加版本信息
4. **备份策略**：定期备份关键数据

### 性能优化

1. **批量操作**：使用批量操作减少网络往返
2. **连接复用**：避免频繁创建和关闭连接
3. **数据压缩**：对大文本数据启用压缩
4. **缓存策略**：合理设置缓存过期时间

### 错误处理

1. **连接重试**：实现连接失败时的自动重试
2. **数据验证**：存储前验证数据格式和完整性
3. **异常处理**：妥善处理各种存储异常
4. **状态监控**：监控存储系统的健康状态

---

## 🔍 故障排除

### 常见问题

1. **连接失败**
   - 检查 Redis 服务器是否运行
   - 验证连接参数是否正确
   - 确认网络连通性

2. **数据丢失**
   - 检查过期时间设置
   - 验证数据序列化是否正确
   - 确认存储空间是否充足

3. **性能问题**
   - 优化数据结构和查询模式
   - 检查内存使用情况
   - 考虑数据分片和集群

### 调试技巧

```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 检查连接状态
if redis_manager.client:
    print("Redis 连接正常")
else:
    print("Redis 连接异常")

# 监控性能
import time
start_time = time.time()
await redis_manager.save_item("test", "data")
end_time = time.time()
print(f"写入操作耗时: {end_time - start_time:.3f}秒")

# 检查数据完整性
metadata = await redis_manager.get_metadata("important_data")
if metadata and "data" in metadata:
    print("数据完整性检查通过")
else:
    print("数据完整性检查失败")
```

---

*最后更新: 2026-01-08*
