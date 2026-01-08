# redis_manager.py - Redis 管理器

redis_manager.py 模块提供 Redis 管理功能，负责连接和操作 Redis 数据库。

---

## 📁 文件路径

```
src/autospider/common/storage/redis_manager.py
```

---

## 📑 函数目录

### 🚀 核心类
- `RedisManager` - Redis 管理器主类

### 🔧 主要方法
- `connect()` - 连接 Redis
- `save_item()` - 保存单个项目
- `load_items()` - 加载所有项目
- `clear()` - 清空数据

---

## 🚀 核心功能

### RedisManager

Redis 管理器，负责连接和操作 Redis 数据库。

```python
from autospider.common.storage.redis_manager import RedisManager

# 创建 Redis 管理器
manager = RedisManager(
    host="localhost",
    port=6379,
    password=None,
    db=0,
    key_prefix="autospider:urls"
)

# 连接 Redis
client = await manager.connect()

# 保存项目
await manager.save_item("https://example.com/product/1")

# 加载所有项目
items = await manager.load_items()
print(f"已加载 {len(items)} 个项目")
```

---

## 💡 特性说明

### 连接管理

自动管理 Redis 连接。

### 键前缀

使用键前缀避免冲突。

---

## 🔧 使用示例

### 基本使用

```python
from autospider.common.storage.redis_manager import RedisManager

# 创建 Redis 管理器
manager = RedisManager(
    host="localhost",
    port=6379,
    password=None,
    db=0,
    key_prefix="autospider:urls"
)

# 连接 Redis
client = await manager.connect()

# 保存项目
await manager.save_item("https://example.com/product/1")
await manager.save_item("https://example.com/product/2")

# 加载所有项目
items = await manager.load_items()
print(f"已加载 {len(items)} 个项目")
for item in items:
    print(f"  {item}")
```

---

## 📚 方法参考

### RedisManager 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `connect()` | 无 | RedisClient \| None | 连接 Redis |
| `save_item()` | item | None | 保存单个项目 |
| `load_items()` | 无 | list[str] | 加载所有项目 |
| `clear()` | 无 | None | 清空数据 |

---

*最后更新: 2026-01-08*
