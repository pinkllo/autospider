# URL 通道 (URL Channel)

`channel` 模块提供生产-消费模式的 URL 传输机制，支持多种后端实现，用于解耦列表页采集和详情页抽取。

---

## 📁 主要文件

- `base.py`: 定义抽象基类 `URLChannel` 和数据模型 `URLTask`。
- `memory_channel.py`: 基于 `asyncio.Queue` 的进程内内存通道（最快）。
- `file_channel.py`: 基于本地文件的“尾随”读取模式（支持持久化，低耦合）。
- `redis_channel.py`: 基于 Redis Stream 的可靠通道（生产级并发）。
- `factory.py`: 通道创建工厂。

---

## 🚀 核心组件

### `URLTask`
传输的最小单位：
- `url`: 目标 URL。
- `ack()`: 确认处理成功的异步回调。
- `fail(reason)`: 标记处理失败的异步回调。

### `URLChannel` (接口)
- `publish(url)`: 发布一个 URL。
- `fetch(max_items, timeout_s)`: 批量获取任务。

---

## 🔧 使用示例

### 1. 发布 URL
```python
from autospider.common.channel import create_url_channel
from autospider.common.config import config

channel = create_url_channel(config.pipeline.mode)
await channel.publish("https://example.com/news/1")
```

### 2. 消费任务并确认
```python
tasks = await channel.fetch(max_items=5)
for task in tasks:
    process(task.url)
    if success:
        await task.ack()
    else:
        await task.fail("Extraction failed")
```

---

*最后更新: 2026-01-27*
