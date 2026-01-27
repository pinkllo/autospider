# redis_manager.py - Redis 队列管理器

`redis_manager.py` 模块提供基于 Redis Stream 的可靠队列管理功能，支持 ACK 机制、多消费者组和任务重试。

---

## 📁 文件路径

```
src/autospider/common/storage/redis_manager.py
```

---

## 📑 核心类

### `RedisQueueManager`

Redis 可靠队列管理器。

#### 构造函数参数
- `host`: Redis 服务器地址 (默认: "localhost")
- `port`: Redis 端口 (默认: 6379)
- `key_prefix`: 存储键的前缀，用于区分不同的任务队列 (默认: "autospider:urls")

---

## 🚀 核心功能

### 1. 生产者：推入任务
```python
from autospider.common.storage.redis_manager import RedisQueueManager

manager = RedisQueueManager(key_prefix="my_task")
await manager.connect()

# 推入单个任务（内置去重机制）
await manager.push_task("https://example.com/item/1", metadata={"priority": "high"})
```

### 2. 消费者：获取与确认任务
```python
# 获取任务 (阻塞模式)
tasks = await manager.fetch_task(consumer_name="worker_1", block_ms=5000)

for stream_id, data_id, data in tasks:
    try:
        # 处理业务逻辑
        print(f"Processing {data['url']}")
        
        # 成功后 ACK
        await manager.ack_task(stream_id)
    except Exception as e:
        # 失败处理：增加重试计数或移入死信队列
        await manager.fail_task(stream_id, data_id, error_msg=str(e))
```

### 3. 故障转移：捞回超时任务
```python
# 捞回超过 5 分钟未确认的任务
recovered_tasks = await manager.recover_stale_tasks(
    consumer_name="worker_1", 
    max_idle_ms=300000
)
```

---

## 💡 技术架构

### 存储结构
1. **Data Hash**: `{key_prefix}:data` 存储全量数据及其元状态，Field 为 URL 的 Hash ID。
2. **Task Stream**: `{key_prefix}:stream` 任务分发队列。
3. **Consumer Group**: `{key_prefix}:workers` 实现多进程负载均衡。

### 状态流转
- **PUSH**: 存入 Hash 并发送到 Stream。
- **FETCH**: 消费者通过组读取，消息进入 PEL (Pending Entries List)。
- **ACK**: 消息从 PEL 移除，标记为完成。
- **FAIL**: 更新重试次数。如超过 `max_retries`，则 ACK 并移入 `{key_prefix}:dead_letter`。

---

## 📚 方法参考

| 方法 | 说明 |
|------|------|
| `connect()` | 连接到 Redis 并确保 Consumer Group 存在。 |
| `push_task(item, metadata)` | 推入任务。如果 item (URL) 已存在则返回 False。 |
| `fetch_task(consumer_name, block_ms, count)` | 从组中获取任务。 |
| `ack_task(stream_id)` | 确认任务完成，从 PEL 移除。 |
| `fail_task(stream_id, data_id, error_msg, max_retries)` | 标记失败。支持自动重试逻辑。 |
| `recover_stale_tasks(consumer_name, max_idle_ms)` | 自动捞回其他消费者崩溃后遗留的超时任务。 |
| `get_stats()` | 获取队列统计信息（总数、Stream 长度、PEL 堆积数）。 |

---

*最后更新: 2026-01-27*
