# Redis 逻辑删除功能说明

## 概述

RedisManager 现已支持逻辑删除功能。URL 数据不会被物理删除，而是通过 `deleted` 字段标记为已删除状态。

## 数据结构

### 旧版本（Set）
```
autospider:urls -> Set {url1, url2, url3, ...}
```

### 新版本（Hash）
```
autospider:urls:url1 -> Hash {url: "url1", deleted: "false"}
autospider:urls:url2 -> Hash {url: "url2", deleted: "false"}
autospider:urls:url3 -> Hash {url: "url3", deleted: "true"}
```

每个 URL 都是一个独立的 Hash，包含：
- `url`: URL 本身
- `deleted`: 逻辑删除标志（"true" 或 "false"）

## 主要特性

### 1. 写入时默认未删除
所有新写入的 URL 的 `deleted` 字段都会自动设置为 `"false"`

```python
# 单个保存
await redis_manager.save_url("https://example.com/page1")

# 批量保存
await redis_manager.save_urls_batch([
    "https://example.com/page1",
    "https://example.com/page2",
])
```

### 2. 断点续爬加载所有 URL
`load_urls()` 会返回**所有** URL（包括已逻辑删除的），确保不会重复爬取：

```python
# 加载所有历史URL（包括已删除的）
existing_urls = await redis_manager.load_urls()
# 返回: {"url1", "url2", "url3"}  # url3虽然deleted=true，但仍然会被加载
```

这样做的好处是：即使某个 URL 被标记为删除，爬虫也知道它已经爬过了，不会重新爬取。

### 3. 逻辑删除接口

#### 单个删除
```python
# 标记单个URL为删除
success = await redis_manager.mark_as_deleted("https://example.com/page1")
```

#### 批量删除
```python
# 批量标记删除
urls_to_delete = [
    "https://example.com/page1",
    "https://example.com/page2",
]
success = await redis_manager.mark_as_deleted_batch(urls_to_delete)
```

### 4. 查询接口

#### 检查是否已删除
```python
is_deleted = await redis_manager.is_deleted("https://example.com/page1")
```

#### 获取活跃的 URL
```python
# 获取所有未删除的URL
active_urls = await redis_manager.get_active_urls()
```

#### 统计数量
```python
# 获取总数（包含已删除的）
total_count = await redis_manager.get_count()

# 获取活跃URL数量（未删除的）
active_count = await redis_manager.get_active_count()
```

## 使用示例

```python
from autospider.redis_manager import RedisManager

async def main():
    # 初始化
    redis_manager = RedisManager(
        host="localhost",
        port=6379,
        key_prefix="autospider:urls"
    )
    
    # 连接
    await redis_manager.connect()
    
    # 保存URL
    await redis_manager.save_urls_batch([
        "https://example.com/page1",
        "https://example.com/page2",
        "https://example.com/page3",
    ])
    
    # 断点续爬时加载所有URL（包括已删除的）
    existing_urls = await redis_manager.load_urls()
    print(f"已爬取过的URL: {len(existing_urls)}")
    
    # 标记某些URL为删除（由其他模块调用）
    await redis_manager.mark_as_deleted("https://example.com/page2")
    
    # 获取活跃URL
    active_urls = await redis_manager.get_active_urls()
    print(f"活跃URL: {len(active_urls)}")
    
    # 统计
    print(f"总URL数: {await redis_manager.get_count()}")
    print(f"活跃URL数: {await redis_manager.get_active_count()}")
    
    # 关闭
    await redis_manager.close()
```

## 注意事项

1. **数据迁移**：如果之前使用旧版本（Set结构）存储过数据，需要清空 Redis 或手动迁移数据
2. **删除操作**：逻辑删除由其他模块完成，`RedisManager` 只提供接口
3. **断点续爬**：`load_urls()` 加载所有 URL（包括已删除的），确保不重复爬取
4. **性能**：使用 `scan_iter` 而不是 `keys`，避免阻塞 Redis

## API 清单

| 方法 | 说明 |
|------|------|
| `save_url(url)` | 保存单个URL（deleted=false） |
| `save_urls_batch(urls)` | 批量保存URL（deleted=false） |
| `load_urls()` | 加载所有URL（包括已删除的） |
| `mark_as_deleted(url)` | 标记URL为删除 |
| `mark_as_deleted_batch(urls)` | 批量标记删除 |
| `is_deleted(url)` | 检查URL是否已删除 |
| `get_active_urls()` | 获取所有未删除的URL |
| `get_count()` | 获取总URL数（包含已删除） |
| `get_active_count()` | 获取活跃URL数（未删除） |
