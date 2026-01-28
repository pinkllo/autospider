# URL 通道工厂 (Channel Factory)

`factory.py` 模块负责根据配置动态创建合适的 `URLChannel` 实现。它隐藏了不同后端（内存、文件、Redis）的初始化细节，为流水线提供统一的任务分发入口。

---

## 🚀 核心函数：`create_url_channel`

这是该模块的唯一入口函数，负责实例化通道及其所需的依赖。

### 函数签名
```python
def create_url_channel(
    mode: str | None = None,
    output_dir: str = "output",
    redis_manager: RedisQueueManager | None = None,
) -> tuple[URLChannel, RedisQueueManager | None]
```

### 参数说明
- **`mode`**: 
    - `memory`: 使用 `asyncio.Queue` 实现。适用于单机任务，速度最快，但数据不具备持久性。
    - `file`: 使用本地文件实现。支持任务持久化，多个进程可以通过监控同一个文件进行协作。
    - `redis`: 使用 Redis Stream 实现。支持分布式架构、ACK 确认机制和任务自动重试，适用于大规模生产环境。
    - 如果为 `None`，则默认读取 `config.pipeline.mode`。
- **`output_dir`**: 在 `file` 模式下，用于存放 `urls.txt`（任务列表）和 `urls.cursor`（进度标记）。
- **`redis_manager`**: 可选参数。如果已存在 Redis 连接管理器，可以直接传入，否则在 `redis` 模式下会自动根据 `config.redis` 配置进行初始化。

### 返回值
返回一个元组 `(channel, redis_manager)`：
- `channel`: 创建好的 `URLChannel` 子类实例。
- `redis_manager`: 如果是 Redis 模式，返回创建的 `RedisQueueManager` 实例，否则返回 `None`。

---

## 🔧 示例

### 自动根据配置创建
```python
from autospider.common.channel.factory import create_url_channel

# 默认读取 config.pipeline.mode
channel, manager = create_url_channel()
```

### 强制使用内存模式
```python
channel, _ = create_url_channel(mode="memory")
```

### 强制使用 Redis 模式并配合现有 Manager
```python
from autospider.storage.redis_manager import RedisQueueManager

manager = RedisQueueManager(...)
channel, _ = create_url_channel(mode="redis", redis_manager=manager)
```

---

*最后更新: 2026-01-28*
