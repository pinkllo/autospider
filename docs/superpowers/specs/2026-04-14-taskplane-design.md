# TaskPlane — 通用任务调度控制平面设计规范

> **状态**: Approved  
> **创建日期**: 2026-04-14  
> **作者**: Antigravity + User  

## 1. 概述

TaskPlane 是一个独立的、可复用的任务调度控制平面模块，用于 plan agent 与 execute agent 之间的标准化通信。它提供任务的完整生命周期管理（注册、分发、执行、结果收集）和持久化能力。

### 1.1 核心目标

- **跨项目复用**：作为通用 task orchestration SDK，不绑定 autospider 的 domain model
- **双层存储**：Redis 热数据 + PG 冷数据归档，兼顾性能和持久性
- **混合分发**：同时支持 push 和 pull 两种消费模式
- **简单确认**：任务注册即进入分发队列，无审批门控

### 1.2 设计原则

1. 三层分离：协议层、调度层、存储层各自独立，可独立替换和测试
2. payload 完全泛型：任务载荷为 `dict[str, Any]`，调用方自定义结构
3. 向后兼容：现有 autospider 代码通过适配器层接入，不修改已有 domain model

---

## 2. 架构总览

```
┌─────────────────────────────────────────────────────────┐
│                     调用方 (Agents)                      │
│  ┌──────────────┐                  ┌──────────────────┐ │
│  │  Plan Agent   │                  │  Execute Agent   │ │
│  │              │                  │                  │ │
│  │ submit_      │                  │ pull() /         │ │
│  │ envelope()   │                  │ subscribe()      │ │
│  └──────┬───────┘                  └────────┬─────────┘ │
└─────────┼──────────────────────────────────┼────────────┘
          │                                  │
          ▼                                  ▼
┌─────────────────────────────────────────────────────────┐
│              调度层 (TaskScheduler)                       │
│                                                         │
│  submit_envelope() ─┐    ┌─ pull() / subscribe()        │
│  submit_tickets()   ├────┤  ack_start()                 │
│  cancel_ticket()    │    │  report_result()              │
│  cancel_envelope()  │    │  heartbeat()                  │
│                     │    │  release()                    │
│                     │    │                               │
│  DispatchStrategy ──┘    └── Subscription (push 封装)    │
│                                                         │
│  get_envelope_progress() / get_ticket() / get_result()  │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│              存储层 (TaskStore Protocol)                  │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │           DualLayerStore                          │   │
│  │  ┌─────────────────┐   ┌──────────────────────┐  │   │
│  │  │  RedisHotStore   │   │    PgColdStore        │  │   │
│  │  │                 │   │                      │  │   │
│  │  │ 活跃任务队列     │   │  任务快照/历史归档    │  │   │
│  │  │ 实时状态         │   │  复杂查询             │  │   │
│  │  │ Claim 锁         │   │  永久持久化           │  │   │
│  │  └─────────────────┘   └──────────────────────┘  │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  MemoryStore (测试/降级 fallback)                        │
└─────────────────────────────────────────────────────────┘
```

---

## 3. 协议层 (Protocol Layer)

### 3.1 PlanEnvelope — 计划信封

plan agent 的输出契约，封装一次规划的完整结果。

| 字段 | 类型 | 说明 |
|------|------|------|
| `envelope_id` | `str` | 唯一 ID (UUID) |
| `source_agent` | `str` | 来源 agent 标识 |
| `created_at` | `datetime` | 创建时间 |
| `metadata` | `dict[str, Any]` | 扩展元数据（调用方自定义） |
| `tickets` | `list[TaskTicket]` | 拆分后的任务票据列表 |
| `plan_snapshot` | `dict[str, Any]` | 原始计划快照（只读归档） |

### 3.2 TaskTicket — 任务票据

单个可执行单元，是调度和分发的最小粒度。

| 字段 | 类型 | 说明 |
|------|------|------|
| `ticket_id` | `str` | 唯一 ID (UUID) |
| `envelope_id` | `str` | 所属信封 ID |
| `parent_ticket_id` | `str \| None` | 父票据（支持树形拆分） |
| `status` | `TicketStatus` | 当前状态 |
| `priority` | `int` | 优先级 (0 最高) |
| `payload` | `dict[str, Any]` | 泛型任务载荷（不约束结构） |
| `labels` | `dict[str, str]` | 标签（用于路由和过滤） |
| `assigned_to` | `str \| None` | 分配给哪个 execute agent |
| `created_at` | `datetime` | 创建时间 |
| `updated_at` | `datetime` | 最后更新时间 |
| `attempt_count` | `int` | 已尝试次数 |
| `max_attempts` | `int` | 最大尝试次数 |
| `timeout_seconds` | `int \| None` | 单次执行超时 |
| `result` | `TaskResult \| None` | 执行结果 |

### 3.3 TaskResult — 执行结果

execute agent 的输出契约。

| 字段 | 类型 | 说明 |
|------|------|------|
| `result_id` | `str` | 唯一 ID |
| `ticket_id` | `str` | 所属 ticket ID |
| `status` | `ResultStatus` | success / failed / expanded |
| `output` | `dict[str, Any]` | 泛型结果载荷 |
| `error` | `str` | 错误信息 |
| `artifacts` | `list[dict[str, str]]` | 产物路径列表 |
| `spawned_tickets` | `list[dict]` | 运行时拆分出的子票据 |
| `completed_at` | `datetime` | 完成时间 |

### 3.4 状态机

```
TicketStatus 状态流转：

  REGISTERED ──→ QUEUED ──→ DISPATCHED ──→ RUNNING ──→ COMPLETED
                   │            │              │
                   │            │              ├──→ FAILED ──→ QUEUED (retry)
                   │            │              │
                   │            │              └──→ EXPANDED (拆分子任务)
                   │            │
                   │            └──→ TIMEOUT ──→ QUEUED (retry)
                   │
                   └──→ CANCELLED
```

- `REGISTERED`：已注册，即刻自动转为 `QUEUED`（无门控）
- `QUEUED`：在分发队列中等待
- `DISPATCHED`：已推送给 execute agent 但尚未开始
- `RUNNING`：正在执行中
- `EXPANDED`：执行过程中产生了子任务，当前票据终态
- `COMPLETED` / `FAILED` / `CANCELLED`：终态

---

## 4. 存储层 (Store Layer)

### 4.1 TaskStore 协议

```python
class TaskStore(Protocol):
    # ── Envelope ──
    async def save_envelope(self, envelope: PlanEnvelope) -> None: ...
    async def get_envelope(self, envelope_id: str) -> PlanEnvelope | None: ...

    # ── Ticket CRUD ──
    async def save_ticket(self, ticket: TaskTicket) -> None: ...
    async def save_tickets_batch(self, tickets: list[TaskTicket]) -> None: ...
    async def get_ticket(self, ticket_id: str) -> TaskTicket | None: ...
    async def get_tickets_by_envelope(self, envelope_id: str) -> list[TaskTicket]: ...

    # ── 状态变更 ──
    async def update_status(self, ticket_id: str, status: TicketStatus, **kwargs) -> TaskTicket: ...

    # ── 队列操作 ──
    async def claim_next(self, labels: dict[str, str] | None = None, batch_size: int = 1) -> list[TaskTicket]: ...
    async def release_claim(self, ticket_id: str, reason: str) -> None: ...

    # ── 结果 ──
    async def save_result(self, result: TaskResult) -> None: ...
    async def get_result(self, ticket_id: str) -> TaskResult | None: ...

    # ── 查询 ──
    async def query_tickets(
        self, *, status: TicketStatus | None = None,
        envelope_id: str | None = None,
        labels: dict[str, str] | None = None,
        limit: int = 100,
    ) -> list[TaskTicket]: ...
```

### 4.2 RedisHotStore

Redis 数据结构映射：

| Key 模式 | 类型 | 用途 |
|----------|------|------|
| `ticket:{ticket_id}` | Hash | ticket 完整数据 |
| `envelope:{envelope_id}` | Hash | envelope 元数据 |
| `envelope:{envelope_id}:tids` | Set | envelope 下的 ticket IDs |
| `queue:default` | Sorted Set | 默认分发队列 (score=priority) |
| `queue:label:{key}:{value}` | Sorted Set | 按标签索引的队列 |
| `running:{ticket_id}` | String | claim 锁 (TTL=timeout_seconds) |

- `claim_next` 使用 `ZPOPMIN` 原子操作弹出最高优先任务并设置 claim 锁
- claim 锁带 TTL，超时自动释放回队列（防死锁）

### 4.3 PgColdStore

```sql
CREATE TABLE plan_envelopes (
    envelope_id    VARCHAR(64) PRIMARY KEY,
    source_agent   VARCHAR(128),
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    metadata       JSONB DEFAULT '{}',
    plan_snapshot  JSONB DEFAULT '{}',
    archived_at    TIMESTAMPTZ
);

CREATE TABLE task_tickets (
    ticket_id         VARCHAR(64) PRIMARY KEY,
    envelope_id       VARCHAR(64) REFERENCES plan_envelopes(envelope_id),
    parent_ticket_id  VARCHAR(64),
    status            VARCHAR(32) NOT NULL DEFAULT 'registered',
    priority          INTEGER DEFAULT 0,
    payload           JSONB DEFAULT '{}',
    labels            JSONB DEFAULT '{}',
    assigned_to       VARCHAR(128),
    attempt_count     INTEGER DEFAULT 0,
    max_attempts      INTEGER DEFAULT 3,
    timeout_seconds   INTEGER,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE task_results (
    result_id        VARCHAR(64) PRIMARY KEY,
    ticket_id        VARCHAR(64) REFERENCES task_tickets(ticket_id),
    status           VARCHAR(32) NOT NULL,
    output           JSONB DEFAULT '{}',
    error            TEXT DEFAULT '',
    artifacts        JSONB DEFAULT '[]',
    spawned_tickets  JSONB DEFAULT '[]',
    completed_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_tickets_status ON task_tickets(status);
CREATE INDEX idx_tickets_envelope ON task_tickets(envelope_id);
CREATE INDEX idx_tickets_labels ON task_tickets USING GIN(labels);
CREATE INDEX idx_tickets_priority ON task_tickets(priority, created_at);
```

### 4.4 DualLayerStore 同步策略

| 操作 | 写入顺序 | 读取来源 |
|------|---------|---------|
| `save_ticket` | Redis → PG (async background) | Redis 优先，miss 时回落 PG |
| `update_status` | Redis → PG (async background) | Redis |
| `claim_next` | 仅 Redis | Redis |
| `save_result` | Redis → PG (sync, 保证持久) | PG 优先 |
| `query_tickets` | PG | PG |
| `get_ticket` | Redis 优先，miss 回落 PG | Redis → PG |

归档策略：终态 ticket（COMPLETED / FAILED / CANCELLED）在 Redis 中保留可配置 TTL（默认 1h），PG 永久保存。

---

## 5. 调度层 (Scheduler Layer)

### 5.1 TaskScheduler API

```python
class TaskScheduler:
    def __init__(
        self,
        store: TaskStore,
        *,
        dispatch_strategy: DispatchStrategy = FIFOStrategy(),
        on_ticket_complete: Callable | None = None,
        on_ticket_failed: Callable | None = None,
        on_envelope_complete: Callable | None = None,
    ): ...

    # Plan Agent 侧
    async def submit_envelope(self, envelope: PlanEnvelope) -> SubmitReceipt: ...
    async def submit_tickets(self, envelope_id: str, tickets: list[TaskTicket]) -> list[str]: ...
    async def cancel_ticket(self, ticket_id: str, reason: str = "") -> None: ...
    async def cancel_envelope(self, envelope_id: str, reason: str = "") -> None: ...

    # Execute Agent 侧 (Pull)
    async def pull(self, *, labels: dict[str, str] | None = None, batch_size: int = 1) -> list[TaskTicket]: ...
    async def ack_start(self, ticket_id: str, agent_id: str = "") -> None: ...
    async def report_result(self, result: TaskResult) -> ReportReceipt: ...
    async def heartbeat(self, ticket_id: str) -> None: ...
    async def release(self, ticket_id: str, reason: str = "") -> None: ...

    # Push 模式
    def subscribe(self, handler, *, labels=None, concurrency=1) -> Subscription: ...

    # 查询
    async def get_envelope_progress(self, envelope_id: str) -> EnvelopeProgress: ...
    async def get_ticket(self, ticket_id: str) -> TaskTicket | None: ...
    async def get_result(self, ticket_id: str) -> TaskResult | None: ...
```

### 5.2 分发策略

```python
class DispatchStrategy(Protocol):
    def compute_score(self, ticket: TaskTicket) -> float: ...

class FIFOStrategy:
    """先进先出——按创建时间排序。"""

class PriorityStrategy:
    """优先级优先——按 priority 排序，同优先级按时间。"""

class BatchAwareStrategy:
    """批次感知——同 envelope 的 tickets 倾向一起分发。"""
```

### 5.3 Subscription (Push 模式)

```python
class Subscription:
    """Push 模式本质是 pull 的语法糖，内部维护 polling loop + worker pool。"""

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
```

### 5.4 辅助类型

```python
@dataclass(frozen=True)
class SubmitReceipt:
    envelope_id: str
    ticket_count: int
    queued_at: datetime

@dataclass(frozen=True)
class ReportReceipt:
    ticket_id: str
    final_status: TicketStatus
    retried: bool
    spawned_count: int

@dataclass(frozen=True)
class EnvelopeProgress:
    envelope_id: str
    total: int
    queued: int
    dispatched: int
    running: int
    completed: int
    failed: int
    expanded: int
    cancelled: int
```

---

## 6. 集成层 (autospider 适配)

### 6.1 模块位置

```
src/autospider/
├── taskplane/                        # 通用模块（可独立发布）
│   ├── __init__.py
│   ├── protocol.py                   # PlanEnvelope, TaskTicket, TaskResult, 枚举
│   ├── store/
│   │   ├── __init__.py
│   │   ├── base.py                   # TaskStore Protocol
│   │   ├── redis_store.py            # RedisHotStore
│   │   ├── pg_store.py               # PgColdStore
│   │   ├── dual_store.py             # DualLayerStore
│   │   └── memory_store.py           # MemoryStore（测试/降级）
│   ├── scheduler.py                  # TaskScheduler
│   ├── strategy.py                   # DispatchStrategy 实现
│   ├── subscription.py               # Subscription
│   └── types.py                      # SubmitReceipt, ReportReceipt, EnvelopeProgress
│
├── taskplane_adapter/                # autospider 适配层
│   ├── __init__.py
│   ├── plan_bridge.py                # TaskPlan ↔ PlanEnvelope
│   ├── subtask_bridge.py             # SubTask ↔ TaskTicket
│   ├── result_bridge.py              # SubTaskRuntimeState ↔ TaskResult
│   └── graph_integration.py          # graph node 接入逻辑
```

### 6.2 适配器

- `PlanBridge.to_envelope(plan)` — TaskPlan → PlanEnvelope
- `PlanBridge.from_envelope(envelope)` — PlanEnvelope → TaskPlan
- `SubtaskBridge.to_ticket(subtask)` — SubTask → TaskTicket
- `SubtaskBridge.from_ticket(ticket)` — TaskTicket → SubTask
- `ResultBridge.to_result(runtime_state)` — SubTaskRuntimeState → TaskResult
- `ResultBridge.from_result(result)` — TaskResult → SubTaskRuntimeState

### 6.3 Graph 节点改造点

| 文件 | 变更 |
|------|------|
| `capability_nodes.py` → `plan_node` | 增加 `scheduler.submit_envelope()` |
| `multi_dispatch.py` → `initialize_multi_dispatch` | 从 `scheduler.pull()` 获取 batch |
| `multi_dispatch.py` → `finalize_subtask_flow` | 增加 `scheduler.report_result()` |
| `multi_dispatch.py` → `merge_dispatch_round` | 用 `scheduler.get_envelope_progress()` |
| `multi_dispatch.py` → `complete_dispatch` | 用 `scheduler.query_tickets()` |
| `planner/runtime.py` → `PlanMutationService` | expand 时调用 `scheduler.submit_tickets()` |

### 6.4 向后兼容

- 现有 `SubTask`、`TaskPlan`、`SubTaskRuntimeState` 不做任何修改
- `MemoryStore` 作为默认 fallback，不配置 Redis/PG 时仍可运行
- 现有 `multi_dispatch_subgraph` 保留结构，仅在关键点插入 scheduler 调用

---

## 7. 错误处理

### 7.1 Ticket 级别容错

- 失败时检查 `attempt_count < max_attempts`，满足则自动 retry（回到 QUEUED）
- 超出重试上限则标记 FAILED，触发 `on_ticket_failed` 回调

### 7.2 Claim 超时

- Redis claim 锁带 TTL，execute agent 需定期调用 `heartbeat()` 续期
- 后台 reaper 协程定期扫描超时的 RUNNING tickets，自动释放回队列

### 7.3 存储降级

| 场景 | 行为 |
|------|------|
| Redis 不可用 | 降级到 PG-only 模式 |
| PG 不可用 | Redis 继续工作，冷数据归档延迟 |
| 双层都不可用 | 回退到 MemoryStore |

---

## 8. 测试策略

```
tests/unit/taskplane/           # 核心模块单元测试 (MemoryStore, 零依赖)
tests/unit/taskplane_adapter/   # 适配器单元测试
tests/integration/taskplane/    # Redis/PG 集成测试
```

- scheduler 核心逻辑 100% 用 `MemoryStore`，标记 `@pytest.mark.smoke`
- Redis/PG 集成测试标记 `@pytest.mark.integration`
- 所有异步测试使用 `@pytest.mark.asyncio`

---

## 9. 配置

```python
@dataclass
class TaskPlaneConfig:
    redis_url: str = ""
    pg_url: str = ""
    fallback_to_memory: bool = True
    default_strategy: str = "priority"
    default_max_attempts: int = 3
    default_timeout_seconds: int = 600
    redis_hot_ttl_seconds: int = 3600
    reaper_interval_seconds: int = 30
    max_subscription_concurrency: int = 32
```

---

## 10. 性能目标

| 指标 | 目标 |
|------|------|
| `submit_envelope`（100 tickets） | < 50ms |
| `pull`（单个） | < 5ms |
| `report_result` | < 10ms |
| `get_envelope_progress` | < 20ms |
| 并发 subscribe workers | 默认 max 32 |
| Redis 热数据 TTL | 终态 1h |
| Reaper 间隔 | 30s |
