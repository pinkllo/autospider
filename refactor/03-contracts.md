# 03 · 契约设计

本文档定义新架构下的全部外部与跨层契约：DB schema、Redis key 规范、消息队列、Saga 编排、统一返回壳 `ResultEnvelope`、日志契约、产物目录结构。**落地时须与本文档对照**；变更任何契约都必须更新本文档并走 ADR。

---

## 1. 数据库 Schema（新）

### 1.1 设计原则

- 每个 Bounded Context **拥有自己的表空间**，不跨 Context 直接 JOIN；跨 Context 需要的数据通过 Domain Event 复制。
- 表名前缀用 Context 名缩写（`pl_` planning、`cl_` collection、`ex_` experience、`ch_` chat）。
- 所有表都有 `created_at` / `updated_at`；状态字段用短枚举字符串（而非 int 编码）。
- JSON 字段用 `JSONB`（PostgreSQL）；如切换 MySQL 用 `JSON` + 查询迁移。
- Alembic 管理迁移，**阶段 1 产出 `0001_init.py`**，之后每个 schema 变更一个 migration。

### 1.2 表清单

#### Planning Context

```sql
-- pl_plans: TaskPlan 聚合
CREATE TABLE pl_plans (
    plan_id       UUID         PRIMARY KEY,
    request_id    UUID         NOT NULL,
    intent        TEXT         NOT NULL,        -- 用户意图摘要
    status        VARCHAR(20)  NOT NULL,        -- draft | active | replanned | completed | failed
    snapshot      JSONB        NOT NULL,        -- 完整 TaskPlan 序列化
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX ix_pl_plans_request ON pl_plans(request_id);
CREATE INDEX ix_pl_plans_status  ON pl_plans(status);

-- pl_subtasks: SubTask 实体
CREATE TABLE pl_subtasks (
    subtask_id    UUID         PRIMARY KEY,
    plan_id       UUID         NOT NULL REFERENCES pl_plans(plan_id) ON DELETE CASCADE,
    sequence      INT          NOT NULL,
    kind          VARCHAR(32)  NOT NULL,        -- explore | collect | extract | sediment
    target_url    TEXT         NOT NULL,
    spec          JSONB        NOT NULL,        -- 输入参数
    status        VARCHAR(20)  NOT NULL,        -- pending | running | succeeded | failed | skipped
    attempt       INT          NOT NULL DEFAULT 0,
    last_error    TEXT         NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX ix_pl_subtasks_plan_status ON pl_subtasks(plan_id, status);

-- pl_failure_signals: 失败模式（喂给 replan）
CREATE TABLE pl_failure_signals (
    id            BIGSERIAL    PRIMARY KEY,
    plan_id       UUID         NOT NULL,
    subtask_id    UUID,
    kind          VARCHAR(32)  NOT NULL,        -- runtime | validation | navigation | llm
    signature     TEXT         NOT NULL,        -- 失败指纹（去重用）
    payload       JSONB        NOT NULL,
    occurred_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX ix_pl_failure_signals_plan ON pl_failure_signals(plan_id);
```

#### Collection Context

```sql
-- cl_runs: CollectionRun 聚合（对应旧 task_runs 的精简版）
CREATE TABLE cl_runs (
    run_id        UUID         PRIMARY KEY,
    plan_id       UUID         NOT NULL,        -- 逻辑外键，不强制约束（跨 Context）
    subtask_id    UUID         NOT NULL,
    thread_id     VARCHAR(128) NOT NULL,        -- LangGraph thread
    status        VARCHAR(20)  NOT NULL,        -- running | succeeded | partial | failed
    total_urls    INT          NOT NULL DEFAULT 0,
    success_count INT          NOT NULL DEFAULT 0,
    failure_count INT          NOT NULL DEFAULT 0,
    metrics       JSONB        NOT NULL DEFAULT '{}',
    artifacts_dir TEXT         NOT NULL DEFAULT '',
    started_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    completed_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX ix_cl_runs_plan     ON cl_runs(plan_id);
CREATE INDEX ix_cl_runs_subtask  ON cl_runs(subtask_id);
CREATE INDEX ix_cl_runs_status   ON cl_runs(status);

-- cl_page_results: PageResult（URL 粒度的采集事实）
CREATE TABLE cl_page_results (
    id            BIGSERIAL    PRIMARY KEY,
    run_id        UUID         NOT NULL REFERENCES cl_runs(run_id) ON DELETE CASCADE,
    url           TEXT         NOT NULL,
    status        VARCHAR(20)  NOT NULL,        -- succeeded | failed | skipped
    attempt       INT          NOT NULL DEFAULT 0,
    fields        JSONB        NOT NULL DEFAULT '{}',
    error_kind    VARCHAR(32)  NOT NULL DEFAULT '',
    error_message TEXT         NOT NULL DEFAULT '',
    duration_ms   INT          NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (run_id, url)
);
CREATE INDEX ix_cl_page_results_status ON cl_page_results(run_id, status);

-- cl_field_xpaths: 详情页字段 XPath 统计（保留原表的核心结构）
CREATE TABLE cl_field_xpaths (
    id                BIGSERIAL    PRIMARY KEY,
    domain            VARCHAR(255) NOT NULL,
    field_name        VARCHAR(128) NOT NULL,
    xpath             TEXT         NOT NULL,
    success_count     INT          NOT NULL DEFAULT 0,
    failure_count     INT          NOT NULL DEFAULT 0,
    last_success_at   TIMESTAMPTZ,
    last_failure_at   TIMESTAMPTZ,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (domain, field_name, xpath)
);
```

#### Experience Context

```sql
-- ex_skills: Skill 聚合
CREATE TABLE ex_skills (
    skill_id       UUID         PRIMARY KEY,
    site_host      VARCHAR(255) NOT NULL,
    intent_key     VARCHAR(128) NOT NULL,       -- 归一化的意图标签
    definition     JSONB        NOT NULL,       -- Skill 定义
    success_count  INT          NOT NULL DEFAULT 0,
    failure_count  INT          NOT NULL DEFAULT 0,
    last_used_at   TIMESTAMPTZ,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ix_ex_skills_host_intent ON ex_skills(site_host, intent_key);

-- ex_skill_usages: 使用记录（用于命中率统计）
CREATE TABLE ex_skill_usages (
    id            BIGSERIAL    PRIMARY KEY,
    skill_id      UUID         NOT NULL REFERENCES ex_skills(skill_id) ON DELETE CASCADE,
    run_id        UUID         NOT NULL,
    outcome       VARCHAR(16)  NOT NULL,        -- hit | partial | miss
    metrics       JSONB        NOT NULL DEFAULT '{}',
    recorded_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX ix_ex_usages_skill ON ex_skill_usages(skill_id, recorded_at);
```

#### Chat Context

```sql
-- ch_sessions: ClarificationSession
CREATE TABLE ch_sessions (
    session_id    UUID         PRIMARY KEY,
    status        VARCHAR(20)  NOT NULL,        -- ongoing | finalized | abandoned
    turns         JSONB        NOT NULL DEFAULT '[]',   -- DialogueTurn[] 全量
    clarified     JSONB,                        -- 最终 ClarifiedTask
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX ix_ch_sessions_status ON ch_sessions(status);
```

### 1.3 丢弃的字段（对比旧 `models.py`）

- `tasks`：`registry_id`（未用）、`variant_label`（迁移到 `pl_subtasks.spec.variant`）、`strategy_payload`（合并进 `snapshot`）
- `task_runs`：`pipeline_mode`、`outcome_state`、`promotion_state`、`summary_json`、`world_snapshot`、`site_profile_snapshot`、`failure_patterns`、`plan_knowledge`、`plan_snapshot`、`plan_journal` — 这些属于多个 Context，拆散到 `pl_plans.snapshot`、`pl_failure_signals`、`cl_runs.metrics`、产物文件。
- `task_run_items`：`claim_state`、`durability_state`、`claimed_at`、`durably_committed_at`、`acked_at` — 这些属于队列层面的状态，已由 Redis Streams 管理，不重复存 DB。

### 1.4 Alembic 配置

```text
src/autospider/platform/persistence/sql/alembic/
├── env.py
├── script.py.mako
└── versions/
    └── 0001_init.py   # 阶段 1 commit[1.3] 产出
```

`alembic.ini` 放项目根；`sqlalchemy.url` 读 `AUTOSPIDER_DB_URL` 环境变量。

---

## 2. Redis Key 规范（新）

### 2.1 命名规则

```text
autospider:v1:<kind>:<id>[:sub]
```

- 强制 `autospider:v1:` 前缀，便于未来跨版本迁移
- `kind`：业务对象种类（`plan` / `run` / `skill` / `lock` / `stream` / `ckpt`）
- `id`：UUID 字符串
- 不允许在业务代码中拼接 key，必须调用 `platform/persistence/redis/keys.py` 提供的函数

### 2.2 Key 清单

| Key 模板 | 类型 | 含义 | TTL |
|---|---|---|---|
| `autospider:v1:plan:{plan_id}` | Hash | TaskPlan 快照（热数据，冷数据走 DB） | 无 |
| `autospider:v1:plan:{plan_id}:subtasks` | Hash | `subtask_id -> state_json` | 无 |
| `autospider:v1:run:{run_id}` | Hash | CollectionRun 元数据 | 无 |
| `autospider:v1:run:{run_id}:pages` | List | `page_result_json`（新→旧） | 无 |
| `autospider:v1:run:{run_id}:fields:{subtask_id}` | Hash | `field_name -> value_json` | 无 |
| `autospider:v1:skill:{skill_id}` | Hash | Skill 定义与计数 | 无 |
| `autospider:v1:skill:index:by_host:{host}` | Set | `skill_id` 集合 | 无 |
| `autospider:v1:ckpt:{thread_id}` | （第三方库自管） | LangGraph checkpoint | 无（按 thread 生命周期） |
| `autospider:v1:stream:events.{context}` | Stream | Domain Event 流（`planning` / `collection` / `experience` / `chat`） | `MAXLEN ~ 100000` |
| `autospider:v1:stream:queue.subtask` | Stream | SubTask 工作队列 | `MAXLEN ~ 50000` |
| `autospider:v1:stream:queue.subtask.dead` | Stream | SubTask 死信队列 | `MAXLEN ~ 10000` |
| `autospider:v1:lock:{resource}` | String | 分布式锁（SET NX PX 30000） | 30s，可续期 |

### 2.3 集中注册表（示意）

```python
# platform/persistence/redis/keys.py 接口规范
def plan_key(plan_id: PlanId) -> str: ...
def plan_subtasks_key(plan_id: PlanId) -> str: ...
def run_key(run_id: RunId) -> str: ...
def run_pages_key(run_id: RunId) -> str: ...
def run_fields_key(run_id: RunId, subtask_id: SubTaskId) -> str: ...
def skill_key(skill_id: SkillId) -> str: ...
def skill_index_by_host_key(host: str) -> str: ...
def events_stream_key(context: Literal["planning", "collection", "experience", "chat"]) -> str: ...
def subtask_queue_key() -> str: ...
def subtask_dead_queue_key() -> str: ...
def lock_key(resource: str) -> str: ...
```

**业务代码中出现硬编码字符串如 `f"autospider:..."` 一律视作违规**，由 `ruff` 自定义规则或 review 拦截。

---

## 3. Messaging（消息队列）

### 3.1 事件基类

```python
# platform/messaging/ports.py
from pydantic import BaseModel
from datetime import datetime
from typing import Literal, Protocol, AsyncIterator

class Event(BaseModel):
    id: str                                    # XADD 返回的 stream id
    type: str                                  # "planning.PlanCreated" 等
    run_id: str | None
    trace_id: str
    occurred_at: datetime
    payload: dict

class Messaging(Protocol):
    async def publish(self, stream: str, event: Event) -> str: ...
    async def subscribe(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        block_ms: int = 5000,
        batch: int = 16,
    ) -> AsyncIterator[Event]: ...
    async def ack(self, stream: str, group: str, event_id: str) -> None: ...
    async def fail(self, stream: str, group: str, event_id: str, reason: str) -> None: ...
```

### 3.2 Stream 与 Consumer Group

| Stream | Producer | Consumer Group |
|---|---|---|
| `events.planning` | `contexts/planning/infrastructure/publishers.py` | `consumers.collection`、`consumers.observability` |
| `events.collection` | `contexts/collection/infrastructure/publishers.py` | `consumers.planning`（失败重规划）、`consumers.experience`（沉淀）、`sagas.collection` |
| `events.experience` | `contexts/experience/infrastructure/publishers.py` | `consumers.planning`（后续计划利用已有技能） |
| `events.chat` | `contexts/chat/infrastructure/publishers.py` | `consumers.planning`（澄清完 → 启动规划） |
| `queue.subtask` | `contexts/planning/application/use_cases/decompose_plan.py` | `workers.collection` |
| `queue.subtask.dead` | `platform.messaging` 自动写入 | 人工审查 |

### 3.3 事件目录（稳定契约）

| 事件类型 | payload 字段 | 触发时机 |
|---|---|---|
| `chat.TaskClarified` | `session_id`, `clarified_task` | 澄清完成 |
| `planning.PlanCreated` | `plan_id`, `request_id`, `intent` | 首次规划后 |
| `planning.SubTaskPlanned` | `plan_id`, `subtask_id`, `spec` | 分解出一个 SubTask |
| `planning.PlanReplanned` | `plan_id`, `reason`, `snapshot_version` | 重规划后 |
| `collection.CollectionStarted` | `run_id`, `plan_id`, `subtask_id` | 开始采集 |
| `collection.PageScraped` | `run_id`, `url`, `status`, `duration_ms` | 单页处理完 |
| `collection.FieldExtracted` | `run_id`, `subtask_id`, `field_name`, `value_hash` | 字段提取完 |
| `collection.SubTaskCompleted` | `run_id`, `subtask_id`, `status`, `metrics` | SubTask 结束 |
| `collection.SubTaskFailed` | `run_id`, `subtask_id`, `error_kind`, `signature` | SubTask 失败（供 replan） |
| `collection.CollectionFinalized` | `run_id`, `plan_id`, `status`, `artifacts_dir` | 整个 Plan 的 Collection 阶段完成 |
| `experience.SkillLearned` | `skill_id`, `site_host`, `intent_key` | 沉淀产生新技能 |
| `experience.SkillApplied` | `skill_id`, `run_id`, `outcome` | 使用已有技能 |

### 3.4 重试与死信

- Consumer 处理失败 → 调 `messaging.fail()`；内部实现为：递增 payload 中的 `retry_count`，小于阈值则重回 PEL（pending entries list），等待下次 `XREADGROUP`。
- 超过 `max_retries`（默认 3） → `XADD` 到 `queue.subtask.dead` 并 `XACK` 原 stream。
- 死信由人工或运维脚本处理，不自动丢弃。

---

## 4. Saga 编排

### 4.1 `CollectionSaga`（核心）

```text
[TaskClarified]
     │
     ▼
[create_plan use case] ──► publish PlanCreated
     │
     ▼
[decompose_plan use case] ──► 对每个 SubTask publish SubTaskPlanned + enqueue to queue.subtask
     │
     ▼
[workers.collection] 订阅 queue.subtask:
     ├─ run_subtask use case
     ├─ publish PageScraped / FieldExtracted
     └─ publish SubTaskCompleted | SubTaskFailed
     │
     ▼
[saga.collection] 订阅 events.collection:
     ├─ 所有 SubTask 完成 → 调 finalize_run use case → publish CollectionFinalized
     └─ 任一 SubTask 失败多次 → publish RequestReplan → 进入 recovery_saga
     │
     ▼
[saga.experience] 订阅 CollectionFinalized → sediment_skill use case
```

### 4.2 `RecoverySaga`

```text
[SubTaskFailed 且 retry_count >= 阈值]
     │
     ▼
[saga.recovery] 订阅：
     ├─ 调 classify_runtime_exception use case 归类
     ├─ 调 replan use case 生成新版本 Plan
     └─ 重新入队受影响的 SubTask
```

### 4.3 Saga 实现约束

- Saga 本身无状态（状态全部落在 Redis/Stream 里）
- Saga 代码**只能调 Application Service**，不能直接调 Repository
- Saga 超时与重试策略用 `tenacity` 表达，写在 Saga 模块顶部

---

## 5. `ResultEnvelope`（统一返回壳）

```python
# platform/shared_kernel/result.py
from typing import Generic, Literal, TypeVar
from pydantic import BaseModel
from pathlib import Path

T = TypeVar("T")

class ErrorInfo(BaseModel):
    kind: str                  # "validation" | "llm" | "browser" | "infra" | "domain"
    code: str                  # 稳定的错误码（如 "planning.empty_intent"）
    message: str
    context: dict = {}

class ResultEnvelope(BaseModel, Generic[T]):
    status: Literal["success", "partial", "failed"]
    data: T | None = None
    errors: list[ErrorInfo] = []
    metrics: dict[str, float] = {}
    artifacts_path: Path | None = None
    run_id: str | None = None
    trace_id: str
```

### 使用规则

- **所有** Application Service 与 Composition Use Case 的返回类型必须是 `ResultEnvelope[SomeDTO]`
- `status = "partial"` 仅用于集合用例（如批量字段提取中一部分成功）
- Domain Service / Repository **不**返回 `ResultEnvelope`（保持领域纯净）；由 Application Service 包装

---

## 6. 产物目录（Artifacts）

### 6.1 目录结构

```text
output/
└── runs/
    └── <run_id>/
        ├── manifest.json          # run 元信息
        ├── plan.json              # 最终 TaskPlan 快照
        ├── subtasks/
        │   └── <subtask_id>/
        │       ├── result.json    # ResultEnvelope 序列化
        │       ├── pages.ndjson   # 每行一个 PageResult
        │       └── fields.json    # 提取的字段（聚合）
        ├── events.jsonl           # 本 run 期间所有 Domain Event（append-only）
        ├── trace.jsonl            # 结构化日志（按 run_id 过滤）
        └── summary.md             # 人类可读总结
```

### 6.2 `manifest.json` Schema

```json
{
  "run_id": "uuid",
  "plan_id": "uuid",
  "request": "用户原始请求字符串",
  "started_at": "2025-04-19T01:00:00+00:00",
  "finished_at": "2025-04-19T01:15:00+00:00",
  "status": "success | partial | failed",
  "metrics": {
    "total_urls": 100,
    "success_count": 92,
    "failure_count": 8,
    "duration_ms": 900000
  },
  "trace_id": "hex-string",
  "autospider_version": "0.2.0"
}
```

### 6.3 `summary.md` 模板

```markdown
# Run <run_id>

- Status: ✅ success
- Request: "采集 xxx 网站的商品列表"
- Started: 2025-04-19 01:00 UTC
- Duration: 15m
- Trace: <trace_id>

## Plan
- PlanId: ...
- SubTasks: 3 (3 succeeded)

## Metrics
| Metric | Value |
| --- | --- |
| Total URLs | 100 |
| Success | 92 |
| Failed | 8 |

## Errors
- 2× BrowserTimeout on https://...
- 6× FieldValidation on https://...

## Artifacts
- subtasks/<id>/result.json
- pages.ndjson (92 rows)
```

### 6.4 CLI 末尾渲染

运行结束后，CLI 用 `rich.panel.Panel` 打印 summary（从 `ResultEnvelope.metrics` 与 `artifacts_path` 取数）：

```text
╭─ AutoSpider Run Summary ─────────────────────────────────╮
│ Status      : ✅ success                                   │
│ Run ID      : 4f6c...                                    │
│ Duration    : 15m 02s                                    │
│ URLs        : 92 / 100 succeeded                         │
│ Artifacts   : output/runs/4f6c.../                       │
│ Trace ID    : 9a8b...                                    │
╰──────────────────────────────────────────────────────────╯
```

---

## 7. 日志契约

### 7.1 字段 Schema（loguru sink 输出 JSON）

```json
{
  "ts": "2025-04-19T01:00:00.123+00:00",
  "level": "INFO",
  "event": "collection.subtask.started",
  "layer": "application",
  "context": "collection",
  "module": "autospider.contexts.collection.application.use_cases.run_subtask",
  "run_id": "uuid",
  "trace_id": "hex",
  "subtask_id": "uuid",
  "msg": "starting subtask run",
  "extra": {}
}
```

### 7.2 事件命名规范

- 领域事件镜像：`<context>.<aggregate>.<action>`，如 `planning.plan.created`、`collection.subtask.started`
- 基础设施：`infra.<resource>.<action>`，如 `infra.redis.reconnect`
- 使用稳定的 `event` 名而非自由文本，便于未来聚合查询

### 7.3 Sink 配置

- **Console Sink**：人类可读（彩色、缩进），开发环境
- **File Sink**：`logs/autospider.jsonl`（JSON Lines），Rotation 100 MB × 7
- **Run Sink**：每个 run 一个 `output/runs/<run_id>/trace.jsonl`，在 `RunContext` 生命周期内挂载/卸载

### 7.4 上下文注入

```python
# platform/observability/logging.py（接口示意）
from contextvars import ContextVar
_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)
_trace_id: ContextVar[str] = ContextVar("trace_id", default="")

def set_run_context(run_id: str, trace_id: str) -> None: ...
def clear_run_context() -> None: ...
```

用法：CLI 入口在进入 use case 前 `set_run_context(...)`，loguru 的 `patcher` 自动把这两个变量写入每条日志记录。

---

## 8. 契约变更流程

1. 任何 `03-contracts.md` 涉及的条目变更，**先更新本文档**
2. 同步提一个 ADR（`docs/adr/NNNN-<topic>.md`）
3. 若变更影响 DB → 新增 Alembic migration
4. 若变更影响 Redis key / 事件 → bump prefix 版本（`v1` → `v2`），不允许原位变更语义
5. 若变更影响 `ResultEnvelope` / 产物格式 → 更新 `tests/contracts/` 下的快照测试
