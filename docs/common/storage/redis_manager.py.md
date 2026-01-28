# redis_manager.py - Redis 队列管理器

`redis_manager.py` 模块提供基于 Redis Stream 的可靠队列管理功能。它专为分布式爬虫设计，确保任务在多机并发环境下不丢失、不重复，并具备完善的故障恢复能力。

---

## 📁 文件路径

```
src/autospider/common/storage/redis_manager.py
```

---

## 📑 核心类：`RedisQueueManager`

该类集成了数据持久化、任务分发和状态管理。

### 存储架构 (Architecture)
为了兼顾性能与可靠性，采用了 **Hash + Stream** 的混合结构：
1. **Data Hash (`{prefix}:data`)**: 以 URL 的 Hash 为 Key 存储原始数据和元指标（如创建时间、重试次数、错误记录）。起到“数据字典”和“去重器”的作用。
2. **Task Stream (`{prefix}:stream`)**: 存储指向 Hash Key 的索引（`data_id`）。用于实现任务的分发。
3. **Consumer Group (`{prefix}:workers`)**: 允许多个进程以竞争方式获取任务。

---

## 🚀 核心功能与代码示例

### 1. 生产者：推入任务
推入操作是原子性的。只有当 URL 在 Hash 中不存在时，才会将其加入 Stream 队列。

```python
from autospider.common.storage.redis_manager import RedisQueueManager

manager = RedisQueueManager(host="127.0.0.1", key_prefix="news_spider")
await manager.connect()

# metadata 会随任务保存，方便后续处理
await manager.push_task(
    item="https://example.com/p/123", 
    metadata={"source": "index_page"}
)

# 批量推入（使用 Pipeline 优化速度）
await manager.push_tasks_batch(["url1", "url2"], metadata_list=[...])
```

### 2. 消费者：可靠消费 (ACK 机制)
任务被 fetch 后，会进入该消费者的 **PEL (Pending Entries List)**。如果消费者崩溃而没有发送 ACK，任务将永远停留在 PEL 中。

```python
# 获取任务 (count=5 表示批量获取)
tasks = await manager.fetch_task(consumer_name="node_A", block_ms=2000, count=5)

for stream_id, data_id, data in tasks:
    success = do_work(data['url'])
    
    if success:
        # 显式确认，任务从 PEL 彻底移除
        await manager.ack_task(stream_id)
    else:
        # 标记失败，内部会自动累加重试次数
        await manager.fail_task(stream_id, data_id, error_msg="Timeout")
```

### 3. 故障恢复 (Failover)
如果某个节点（如 `node_A`）在处理中途宕机，其 PEL 中的任务可以通过 `recover_stale_tasks` 被其他正常节点“捞回”。

```python
# 捞回逻辑：寻找超过 300 秒没有任何活动的停滞任务并重新分配给自己
recovered = await manager.recover_stale_tasks(
    consumer_name="node_B", 
    max_idle_ms=300000 
)
```

---

## 🛠️ 方法参考 (API Reference)

| 方法 | 功能描述 |
|------|----------|
| `connect()` | 初始化 Redis 连接，并自动创建消费者组。 |
| `push_task(item, metadata)` | 写入数据。返回 `True` 表示新任务，`False` 表示重复。 |
| `fetch_task(...)` | 从队列获取任务。支持阻塞模式和批量获取。 |
| `ack_task(stream_id)` | 确认任务完成。此步必不可少，否则会导致内存泄漏（PEL 堆积）。 |
| `fail_task(...)` | 处理失败。若重试次数超过 `max_retries`，任务会进入死信队列。 |
| `recover_stale_tasks(...)` | 故障转移核心方法。定期调用可确保任务不因节点离线而丢失。 |
| `get_stats()` | 获取实时监控数据：任务总数、队列积压数、各消费者状态。 |

---

*最后更新: 2026-01-28*
