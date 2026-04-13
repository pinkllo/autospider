# TaskPlane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a generic, cross-project reusable task orchestration control plane (TaskPlane) with protocol layer, dual-layer storage, and push/pull scheduler.

**Architecture:** Three layers — Protocol (data models & state machine), Store (MemoryStore → RedisHotStore → PgColdStore → DualLayerStore), Scheduler (submit/pull/subscribe/report). An autospider-specific adapter layer bridges existing domain models to the generic protocol.

**Tech Stack:** Python 3.10+, Pydantic v2, redis-py (async), SQLAlchemy 2.x, pytest + pytest-asyncio

---

## File Structure

```
src/autospider/taskplane/              # Generic module (no autospider domain imports)
├── __init__.py                        # Public API re-exports
├── protocol.py                        # PlanEnvelope, TaskTicket, TaskResult, enums
├── types.py                           # SubmitReceipt, ReportReceipt, EnvelopeProgress, TaskPlaneConfig
├── strategy.py                        # DispatchStrategy protocol + FIFO/Priority/BatchAware
├── scheduler.py                       # TaskScheduler (main entry point)
├── subscription.py                    # Subscription (push mode wrapper)
├── store/
│   ├── __init__.py                    # Re-exports
│   ├── base.py                        # TaskStore Protocol
│   ├── memory_store.py                # MemoryStore (tests & fallback)
│   ├── redis_store.py                 # RedisHotStore
│   ├── pg_store.py                    # PgColdStore
│   └── dual_store.py                  # DualLayerStore

src/autospider/taskplane_adapter/      # autospider-specific bridges
├── __init__.py
├── plan_bridge.py                     # TaskPlan ↔ PlanEnvelope
├── subtask_bridge.py                  # SubTask ↔ TaskTicket
└── result_bridge.py                   # SubTaskRuntimeState ↔ TaskResult

tests/unit/taskplane/                  # Unit tests (MemoryStore, zero deps)
├── test_protocol.py
├── test_strategy.py
├── test_memory_store.py
├── test_scheduler.py
└── test_subscription.py

tests/unit/taskplane_adapter/          # Adapter unit tests
├── test_plan_bridge.py
├── test_subtask_bridge.py
└── test_result_bridge.py
```

---

### Task 1: Protocol Models — Enums & TicketStatus

**Files:**
- Create: `src/autospider/taskplane/protocol.py`
- Test: `tests/unit/taskplane/test_protocol.py`

- [ ] **Step 1: Write failing tests for enums and status transitions**

```python
# tests/unit/taskplane/test_protocol.py
import pytest
from autospider.taskplane.protocol import TicketStatus, ResultStatus


class TestTicketStatus:
    def test_all_values_exist(self):
        expected = {"registered", "queued", "dispatched", "running",
                    "completed", "failed", "expanded", "timeout", "cancelled"}
        assert {s.value for s in TicketStatus} == expected

    def test_terminal_states(self):
        assert TicketStatus.COMPLETED.is_terminal
        assert TicketStatus.FAILED.is_terminal
        assert TicketStatus.CANCELLED.is_terminal
        assert TicketStatus.EXPANDED.is_terminal

    def test_non_terminal_states(self):
        assert not TicketStatus.REGISTERED.is_terminal
        assert not TicketStatus.QUEUED.is_terminal
        assert not TicketStatus.RUNNING.is_terminal

    def test_valid_transition_registered_to_queued(self):
        assert TicketStatus.REGISTERED.can_transition_to(TicketStatus.QUEUED)

    def test_invalid_transition_completed_to_running(self):
        assert not TicketStatus.COMPLETED.can_transition_to(TicketStatus.RUNNING)

    def test_valid_transition_running_to_failed(self):
        assert TicketStatus.RUNNING.can_transition_to(TicketStatus.FAILED)

    def test_valid_transition_failed_to_queued_retry(self):
        assert TicketStatus.FAILED.can_transition_to(TicketStatus.QUEUED)


class TestResultStatus:
    def test_all_values_exist(self):
        assert {s.value for s in ResultStatus} == {"success", "failed", "expanded"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/taskplane/test_protocol.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autospider.taskplane'`

- [ ] **Step 3: Create `__init__.py` files and implement enums**

```python
# src/autospider/taskplane/__init__.py
"""TaskPlane — 通用任务调度控制平面。"""

# src/autospider/taskplane/protocol.py
"""Protocol layer: core data models and state machine."""

from __future__ import annotations

from enum import Enum


_TRANSITIONS: dict[str, set[str]] = {
    "registered": {"queued", "cancelled"},
    "queued": {"dispatched", "cancelled"},
    "dispatched": {"running", "timeout", "cancelled"},
    "running": {"completed", "failed", "expanded"},
    "timeout": {"queued", "cancelled"},
    "failed": {"queued", "cancelled"},
    "completed": set(),
    "expanded": set(),
    "cancelled": set(),
}

_TERMINAL: set[str] = {"completed", "failed", "expanded", "cancelled"}


class TicketStatus(str, Enum):
    REGISTERED = "registered"
    QUEUED = "queued"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPANDED = "expanded"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self.value in _TERMINAL

    def can_transition_to(self, target: TicketStatus) -> bool:
        return target.value in _TRANSITIONS.get(self.value, set())


class ResultStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    EXPANDED = "expanded"
```

Also create empty `tests/unit/taskplane/__init__.py` and `tests/unit/__init__.py` if missing.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/taskplane/test_protocol.py -v`
Expected: PASS (all 8 tests)

- [ ] **Step 5: Commit**

```
git add -f src/autospider/taskplane/ tests/unit/taskplane/
git commit -m "feat(taskplane): add TicketStatus and ResultStatus enums with state machine"
```

---

### Task 2: Protocol Models — PlanEnvelope, TaskTicket, TaskResult

**Files:**
- Modify: `src/autospider/taskplane/protocol.py`
- Modify: `tests/unit/taskplane/test_protocol.py`

- [ ] **Step 1: Write failing tests for Pydantic models**

```python
# append to tests/unit/taskplane/test_protocol.py
from datetime import datetime, timezone
from autospider.taskplane.protocol import PlanEnvelope, TaskTicket, TaskResult


class TestTaskTicket:
    def test_create_minimal(self):
        ticket = TaskTicket(ticket_id="t1", envelope_id="e1")
        assert ticket.ticket_id == "t1"
        assert ticket.status == TicketStatus.REGISTERED
        assert ticket.priority == 0
        assert ticket.payload == {}
        assert ticket.attempt_count == 0
        assert ticket.max_attempts == 3

    def test_create_with_payload(self):
        ticket = TaskTicket(
            ticket_id="t1",
            envelope_id="e1",
            payload={"url": "https://example.com"},
            labels={"mode": "collect"},
            priority=5,
        )
        assert ticket.payload["url"] == "https://example.com"
        assert ticket.labels["mode"] == "collect"
        assert ticket.priority == 5

    def test_roundtrip_serialization(self):
        ticket = TaskTicket(ticket_id="t1", envelope_id="e1", payload={"x": 1})
        data = ticket.model_dump(mode="python")
        restored = TaskTicket.model_validate(data)
        assert restored.ticket_id == "t1"
        assert restored.payload == {"x": 1}


class TestPlanEnvelope:
    def test_create_with_tickets(self):
        t1 = TaskTicket(ticket_id="t1", envelope_id="e1")
        t2 = TaskTicket(ticket_id="t2", envelope_id="e1")
        envelope = PlanEnvelope(
            envelope_id="e1",
            source_agent="planner",
            tickets=[t1, t2],
        )
        assert len(envelope.tickets) == 2
        assert envelope.source_agent == "planner"

    def test_empty_envelope(self):
        envelope = PlanEnvelope(envelope_id="e1", source_agent="test")
        assert envelope.tickets == []
        assert envelope.plan_snapshot == {}


class TestTaskResult:
    def test_create_success(self):
        result = TaskResult(
            result_id="r1",
            ticket_id="t1",
            status=ResultStatus.SUCCESS,
            output={"items": 42},
        )
        assert result.status == ResultStatus.SUCCESS
        assert result.output["items"] == 42
        assert result.error == ""
        assert result.spawned_tickets == []

    def test_create_expanded(self):
        result = TaskResult(
            result_id="r2",
            ticket_id="t1",
            status=ResultStatus.EXPANDED,
            spawned_tickets=[{"ticket_id": "t1-child1", "payload": {}}],
        )
        assert len(result.spawned_tickets) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/taskplane/test_protocol.py::TestTaskTicket -v`
Expected: FAIL with `ImportError: cannot import name 'TaskTicket'`

- [ ] **Step 3: Implement Pydantic models in protocol.py**

Append to `src/autospider/taskplane/protocol.py`:

```python
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskTicket(BaseModel):
    ticket_id: str
    envelope_id: str
    parent_ticket_id: str | None = None
    status: TicketStatus = TicketStatus.REGISTERED
    priority: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    assigned_to: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    attempt_count: int = 0
    max_attempts: int = 3
    timeout_seconds: int | None = None
    result: "TaskResult | None" = None


class TaskResult(BaseModel):
    result_id: str
    ticket_id: str
    status: ResultStatus
    output: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    artifacts: list[dict[str, str]] = Field(default_factory=list)
    spawned_tickets: list[dict[str, Any]] = Field(default_factory=list)
    completed_at: datetime = Field(default_factory=_utcnow)


class PlanEnvelope(BaseModel):
    envelope_id: str
    source_agent: str
    created_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)
    tickets: list[TaskTicket] = Field(default_factory=list)
    plan_snapshot: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/taskplane/test_protocol.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```
git add -f src/autospider/taskplane/protocol.py tests/unit/taskplane/test_protocol.py
git commit -m "feat(taskplane): add PlanEnvelope, TaskTicket, TaskResult models"
```

---

### Task 3: Types — SubmitReceipt, ReportReceipt, EnvelopeProgress, Config

**Files:**
- Create: `src/autospider/taskplane/types.py`
- Test: `tests/unit/taskplane/test_types.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/taskplane/test_types.py
from autospider.taskplane.types import (
    EnvelopeProgress,
    ReportReceipt,
    SubmitReceipt,
    TaskPlaneConfig,
)
from autospider.taskplane.protocol import TicketStatus


class TestSubmitReceipt:
    def test_fields(self):
        receipt = SubmitReceipt(envelope_id="e1", ticket_count=5)
        assert receipt.envelope_id == "e1"
        assert receipt.ticket_count == 5
        assert receipt.queued_at is not None


class TestReportReceipt:
    def test_fields(self):
        receipt = ReportReceipt(
            ticket_id="t1",
            final_status=TicketStatus.COMPLETED,
            retried=False,
            spawned_count=0,
        )
        assert receipt.final_status == TicketStatus.COMPLETED


class TestEnvelopeProgress:
    def test_fields(self):
        progress = EnvelopeProgress(envelope_id="e1", total=10, completed=3, failed=1)
        assert progress.total == 10
        assert progress.queued == 0


class TestTaskPlaneConfig:
    def test_defaults(self):
        cfg = TaskPlaneConfig()
        assert cfg.redis_url == ""
        assert cfg.default_max_attempts == 3
        assert cfg.default_timeout_seconds == 600
        assert cfg.fallback_to_memory is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/taskplane/test_types.py -v`
Expected: FAIL

- [ ] **Step 3: Implement types.py**

```python
# src/autospider/taskplane/types.py
"""Auxiliary types: receipts, progress, configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .protocol import TicketStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class SubmitReceipt:
    envelope_id: str
    ticket_count: int
    queued_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True, slots=True)
class ReportReceipt:
    ticket_id: str
    final_status: TicketStatus
    retried: bool
    spawned_count: int


@dataclass(frozen=True, slots=True)
class EnvelopeProgress:
    envelope_id: str
    total: int = 0
    queued: int = 0
    dispatched: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    expanded: int = 0
    cancelled: int = 0


@dataclass(slots=True)
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

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/taskplane/test_types.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
git add -f src/autospider/taskplane/types.py tests/unit/taskplane/test_types.py
git commit -m "feat(taskplane): add SubmitReceipt, ReportReceipt, EnvelopeProgress, TaskPlaneConfig"
```

---

### Task 4: Dispatch Strategies

**Files:**
- Create: `src/autospider/taskplane/strategy.py`
- Test: `tests/unit/taskplane/test_strategy.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/taskplane/test_strategy.py
from datetime import datetime, timezone, timedelta
from autospider.taskplane.protocol import TaskTicket
from autospider.taskplane.strategy import (
    FIFOStrategy,
    PriorityStrategy,
    BatchAwareStrategy,
)


def _ticket(tid: str, eid: str = "e1", priority: int = 0, offset_s: int = 0) -> TaskTicket:
    return TaskTicket(
        ticket_id=tid,
        envelope_id=eid,
        priority=priority,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset_s),
    )


class TestFIFOStrategy:
    def test_earlier_ticket_has_lower_score(self):
        s = FIFOStrategy()
        t1 = _ticket("a", offset_s=0)
        t2 = _ticket("b", offset_s=10)
        assert s.compute_score(t1) < s.compute_score(t2)


class TestPriorityStrategy:
    def test_lower_priority_value_has_lower_score(self):
        s = PriorityStrategy()
        t_high = _ticket("a", priority=0)
        t_low = _ticket("b", priority=5)
        assert s.compute_score(t_high) < s.compute_score(t_low)

    def test_same_priority_ordered_by_time(self):
        s = PriorityStrategy()
        t1 = _ticket("a", priority=1, offset_s=0)
        t2 = _ticket("b", priority=1, offset_s=10)
        assert s.compute_score(t1) < s.compute_score(t2)


class TestBatchAwareStrategy:
    def test_same_envelope_has_close_scores(self):
        s = BatchAwareStrategy()
        t1 = _ticket("a", eid="e1", priority=0, offset_s=0)
        t2 = _ticket("b", eid="e1", priority=0, offset_s=1)
        t3 = _ticket("c", eid="e2", priority=0, offset_s=0)
        diff_same = abs(s.compute_score(t1) - s.compute_score(t2))
        diff_diff = abs(s.compute_score(t1) - s.compute_score(t3))
        # same envelope tickets should have closer scores than different envelopes
        # (unless they happen to hash close, which is unlikely)
        assert diff_same < 1e9 or diff_diff > diff_same
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/taskplane/test_strategy.py -v`
Expected: FAIL

- [ ] **Step 3: Implement strategies**

```python
# src/autospider/taskplane/strategy.py
"""Dispatch strategies that control ticket ordering in the queue."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .protocol import TaskTicket


@runtime_checkable
class DispatchStrategy(Protocol):
    def compute_score(self, ticket: TaskTicket) -> float: ...


class FIFOStrategy:
    """First-in-first-out: ordered by creation time."""

    def compute_score(self, ticket: TaskTicket) -> float:
        return ticket.created_at.timestamp()


class PriorityStrategy:
    """Priority-first: lower priority value = higher urgency. Ties broken by time."""

    def compute_score(self, ticket: TaskTicket) -> float:
        return ticket.priority * 1e12 + ticket.created_at.timestamp()


class BatchAwareStrategy:
    """Batch-aware: tickets from the same envelope cluster together."""

    def compute_score(self, ticket: TaskTicket) -> float:
        envelope_hash = hash(ticket.envelope_id) % 1000
        return envelope_hash * 1e9 + ticket.priority * 1e6 + ticket.created_at.timestamp()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/taskplane/test_strategy.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
git add -f src/autospider/taskplane/strategy.py tests/unit/taskplane/test_strategy.py
git commit -m "feat(taskplane): add FIFO, Priority, BatchAware dispatch strategies"
```

---

### Task 5: TaskStore Protocol & MemoryStore

**Files:**
- Create: `src/autospider/taskplane/store/__init__.py`
- Create: `src/autospider/taskplane/store/base.py`
- Create: `src/autospider/taskplane/store/memory_store.py`
- Test: `tests/unit/taskplane/test_memory_store.py`

- [ ] **Step 1: Write failing tests for MemoryStore**

```python
# tests/unit/taskplane/test_memory_store.py
import pytest
from autospider.taskplane.protocol import (
    PlanEnvelope,
    TaskTicket,
    TaskResult,
    TicketStatus,
    ResultStatus,
)
from autospider.taskplane.store.memory_store import MemoryStore
from autospider.taskplane.strategy import PriorityStrategy


@pytest.fixture
def store():
    return MemoryStore(strategy=PriorityStrategy())


@pytest.fixture
def envelope():
    return PlanEnvelope(envelope_id="e1", source_agent="test")


@pytest.fixture
def ticket():
    return TaskTicket(ticket_id="t1", envelope_id="e1", status=TicketStatus.QUEUED)


class TestMemoryStoreEnvelope:
    async def test_save_and_get(self, store, envelope):
        await store.save_envelope(envelope)
        got = await store.get_envelope("e1")
        assert got is not None
        assert got.envelope_id == "e1"

    async def test_get_missing(self, store):
        assert await store.get_envelope("missing") is None


class TestMemoryStoreTicket:
    async def test_save_and_get(self, store, ticket):
        await store.save_ticket(ticket)
        got = await store.get_ticket("t1")
        assert got is not None
        assert got.ticket_id == "t1"

    async def test_batch_save(self, store):
        tickets = [
            TaskTicket(ticket_id="t1", envelope_id="e1", status=TicketStatus.QUEUED),
            TaskTicket(ticket_id="t2", envelope_id="e1", status=TicketStatus.QUEUED),
        ]
        await store.save_tickets_batch(tickets)
        assert await store.get_ticket("t1") is not None
        assert await store.get_ticket("t2") is not None

    async def test_update_status(self, store, ticket):
        await store.save_ticket(ticket)
        updated = await store.update_status("t1", TicketStatus.DISPATCHED)
        assert updated.status == TicketStatus.DISPATCHED

    async def test_get_by_envelope(self, store):
        t1 = TaskTicket(ticket_id="t1", envelope_id="e1", status=TicketStatus.QUEUED)
        t2 = TaskTicket(ticket_id="t2", envelope_id="e1", status=TicketStatus.QUEUED)
        t3 = TaskTicket(ticket_id="t3", envelope_id="e2", status=TicketStatus.QUEUED)
        await store.save_tickets_batch([t1, t2, t3])
        result = await store.get_tickets_by_envelope("e1")
        assert len(result) == 2


class TestMemoryStoreClaim:
    async def test_claim_returns_highest_priority(self, store):
        t_low = TaskTicket(ticket_id="t1", envelope_id="e1", status=TicketStatus.QUEUED, priority=5)
        t_high = TaskTicket(ticket_id="t2", envelope_id="e1", status=TicketStatus.QUEUED, priority=0)
        await store.save_tickets_batch([t_low, t_high])
        claimed = await store.claim_next(batch_size=1)
        assert len(claimed) == 1
        assert claimed[0].ticket_id == "t2"

    async def test_claim_empty_queue(self, store):
        claimed = await store.claim_next(batch_size=1)
        assert claimed == []

    async def test_claim_respects_batch_size(self, store):
        for i in range(5):
            t = TaskTicket(ticket_id=f"t{i}", envelope_id="e1", status=TicketStatus.QUEUED)
            await store.save_ticket(t)
        claimed = await store.claim_next(batch_size=3)
        assert len(claimed) == 3

    async def test_release_claim(self, store):
        t = TaskTicket(ticket_id="t1", envelope_id="e1", status=TicketStatus.QUEUED)
        await store.save_ticket(t)
        await store.claim_next(batch_size=1)
        await store.release_claim("t1", reason="retry")
        got = await store.get_ticket("t1")
        assert got.status == TicketStatus.QUEUED


class TestMemoryStoreResult:
    async def test_save_and_get_result(self, store):
        result = TaskResult(result_id="r1", ticket_id="t1", status=ResultStatus.SUCCESS)
        await store.save_result(result)
        got = await store.get_result("t1")
        assert got is not None
        assert got.result_id == "r1"

    async def test_get_missing_result(self, store):
        assert await store.get_result("missing") is None


class TestMemoryStoreQuery:
    async def test_query_by_status(self, store):
        t1 = TaskTicket(ticket_id="t1", envelope_id="e1", status=TicketStatus.QUEUED)
        t2 = TaskTicket(ticket_id="t2", envelope_id="e1", status=TicketStatus.COMPLETED)
        await store.save_tickets_batch([t1, t2])
        result = await store.query_tickets(status=TicketStatus.QUEUED)
        assert len(result) == 1
        assert result[0].ticket_id == "t1"

    async def test_query_by_envelope(self, store):
        t1 = TaskTicket(ticket_id="t1", envelope_id="e1", status=TicketStatus.QUEUED)
        t2 = TaskTicket(ticket_id="t2", envelope_id="e2", status=TicketStatus.QUEUED)
        await store.save_tickets_batch([t1, t2])
        result = await store.query_tickets(envelope_id="e1")
        assert len(result) == 1

    async def test_query_by_labels(self, store):
        t1 = TaskTicket(ticket_id="t1", envelope_id="e1", status=TicketStatus.QUEUED, labels={"mode": "collect"})
        t2 = TaskTicket(ticket_id="t2", envelope_id="e1", status=TicketStatus.QUEUED, labels={"mode": "expand"})
        await store.save_tickets_batch([t1, t2])
        result = await store.query_tickets(labels={"mode": "collect"})
        assert len(result) == 1
        assert result[0].ticket_id == "t1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/taskplane/test_memory_store.py -v`
Expected: FAIL

- [ ] **Step 3: Implement TaskStore protocol and MemoryStore**

创建 `src/autospider/taskplane/store/__init__.py`:
```python
from .base import TaskStore
from .memory_store import MemoryStore

__all__ = ["TaskStore", "MemoryStore"]
```

创建 `src/autospider/taskplane/store/base.py`:
```python
"""TaskStore protocol — all backends must implement this interface."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..protocol import PlanEnvelope, TaskResult, TaskTicket, TicketStatus


@runtime_checkable
class TaskStore(Protocol):
    async def save_envelope(self, envelope: PlanEnvelope) -> None: ...
    async def get_envelope(self, envelope_id: str) -> PlanEnvelope | None: ...

    async def save_ticket(self, ticket: TaskTicket) -> None: ...
    async def save_tickets_batch(self, tickets: list[TaskTicket]) -> None: ...
    async def get_ticket(self, ticket_id: str) -> TaskTicket | None: ...
    async def get_tickets_by_envelope(self, envelope_id: str) -> list[TaskTicket]: ...

    async def update_status(self, ticket_id: str, status: TicketStatus, **kwargs: Any) -> TaskTicket: ...

    async def claim_next(self, labels: dict[str, str] | None = None, batch_size: int = 1) -> list[TaskTicket]: ...
    async def release_claim(self, ticket_id: str, reason: str) -> None: ...

    async def save_result(self, result: TaskResult) -> None: ...
    async def get_result(self, ticket_id: str) -> TaskResult | None: ...

    async def query_tickets(
        self,
        *,
        status: TicketStatus | None = None,
        envelope_id: str | None = None,
        labels: dict[str, str] | None = None,
        limit: int = 100,
    ) -> list[TaskTicket]: ...
```

创建 `src/autospider/taskplane/store/memory_store.py`:
```python
"""In-memory TaskStore for tests and fallback."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..protocol import PlanEnvelope, TaskResult, TaskTicket, TicketStatus
from ..strategy import DispatchStrategy, PriorityStrategy


class MemoryStore:
    def __init__(self, *, strategy: DispatchStrategy | None = None) -> None:
        self._strategy = strategy or PriorityStrategy()
        self._envelopes: dict[str, PlanEnvelope] = {}
        self._tickets: dict[str, TaskTicket] = {}
        self._results: dict[str, TaskResult] = {}

    async def save_envelope(self, envelope: PlanEnvelope) -> None:
        self._envelopes[envelope.envelope_id] = envelope

    async def get_envelope(self, envelope_id: str) -> PlanEnvelope | None:
        return self._envelopes.get(envelope_id)

    async def save_ticket(self, ticket: TaskTicket) -> None:
        self._tickets[ticket.ticket_id] = ticket

    async def save_tickets_batch(self, tickets: list[TaskTicket]) -> None:
        for ticket in tickets:
            self._tickets[ticket.ticket_id] = ticket

    async def get_ticket(self, ticket_id: str) -> TaskTicket | None:
        return self._tickets.get(ticket_id)

    async def get_tickets_by_envelope(self, envelope_id: str) -> list[TaskTicket]:
        return [t for t in self._tickets.values() if t.envelope_id == envelope_id]

    async def update_status(self, ticket_id: str, status: TicketStatus, **kwargs: Any) -> TaskTicket:
        ticket = self._tickets[ticket_id]
        updates: dict[str, Any] = {"status": status, "updated_at": datetime.now(timezone.utc)}
        updates.update(kwargs)
        updated = ticket.model_copy(update=updates)
        self._tickets[ticket_id] = updated
        return updated

    async def claim_next(
        self, labels: dict[str, str] | None = None, batch_size: int = 1
    ) -> list[TaskTicket]:
        candidates = [
            t for t in self._tickets.values()
            if t.status == TicketStatus.QUEUED
            and (labels is None or all(t.labels.get(k) == v for k, v in labels.items()))
        ]
        candidates.sort(key=lambda t: self._strategy.compute_score(t))
        claimed: list[TaskTicket] = []
        for ticket in candidates[:batch_size]:
            updated = await self.update_status(ticket.ticket_id, TicketStatus.DISPATCHED)
            claimed.append(updated)
        return claimed

    async def release_claim(self, ticket_id: str, reason: str) -> None:
        await self.update_status(ticket_id, TicketStatus.QUEUED)

    async def save_result(self, result: TaskResult) -> None:
        self._results[result.ticket_id] = result

    async def get_result(self, ticket_id: str) -> TaskResult | None:
        return self._results.get(ticket_id)

    async def query_tickets(
        self,
        *,
        status: TicketStatus | None = None,
        envelope_id: str | None = None,
        labels: dict[str, str] | None = None,
        limit: int = 100,
    ) -> list[TaskTicket]:
        result: list[TaskTicket] = []
        for t in self._tickets.values():
            if status is not None and t.status != status:
                continue
            if envelope_id is not None and t.envelope_id != envelope_id:
                continue
            if labels is not None and not all(t.labels.get(k) == v for k, v in labels.items()):
                continue
            result.append(t)
            if len(result) >= limit:
                break
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/taskplane/test_memory_store.py -v`
Expected: PASS (all 12 tests)

- [ ] **Step 5: Commit**

```
git add -f src/autospider/taskplane/store/ tests/unit/taskplane/test_memory_store.py
git commit -m "feat(taskplane): add TaskStore protocol and MemoryStore implementation"
```

---

### Task 6: TaskScheduler — Core submit/pull/report flow

**Files:**
- Create: `src/autospider/taskplane/scheduler.py`
- Test: `tests/unit/taskplane/test_scheduler.py`

- [ ] **Step 1: Write failing tests for scheduler core flow**

```python
# tests/unit/taskplane/test_scheduler.py
import pytest
from autospider.taskplane.protocol import (
    PlanEnvelope,
    TaskTicket,
    TaskResult,
    TicketStatus,
    ResultStatus,
)
from autospider.taskplane.scheduler import TaskScheduler
from autospider.taskplane.store.memory_store import MemoryStore


@pytest.fixture
def scheduler():
    return TaskScheduler(store=MemoryStore())


def _envelope(n_tickets: int = 3) -> PlanEnvelope:
    tickets = [
        TaskTicket(ticket_id=f"t{i}", envelope_id="e1", payload={"index": i})
        for i in range(n_tickets)
    ]
    return PlanEnvelope(envelope_id="e1", source_agent="test", tickets=tickets)


class TestSubmit:
    async def test_submit_envelope(self, scheduler):
        receipt = await scheduler.submit_envelope(_envelope(3))
        assert receipt.envelope_id == "e1"
        assert receipt.ticket_count == 3

    async def test_tickets_become_queued_after_submit(self, scheduler):
        await scheduler.submit_envelope(_envelope(2))
        ticket = await scheduler.get_ticket("t0")
        assert ticket.status == TicketStatus.QUEUED

    async def test_submit_additional_tickets(self, scheduler):
        await scheduler.submit_envelope(_envelope(1))
        new_tickets = [TaskTicket(ticket_id="t_new", envelope_id="e1")]
        ids = await scheduler.submit_tickets("e1", new_tickets)
        assert ids == ["t_new"]


class TestPullAndReport:
    async def test_pull_returns_tickets(self, scheduler):
        await scheduler.submit_envelope(_envelope(3))
        pulled = await scheduler.pull(batch_size=2)
        assert len(pulled) == 2

    async def test_ack_start_transitions_to_running(self, scheduler):
        await scheduler.submit_envelope(_envelope(1))
        pulled = await scheduler.pull(batch_size=1)
        await scheduler.ack_start(pulled[0].ticket_id, agent_id="worker-1")
        ticket = await scheduler.get_ticket(pulled[0].ticket_id)
        assert ticket.status == TicketStatus.RUNNING

    async def test_report_success(self, scheduler):
        await scheduler.submit_envelope(_envelope(1))
        pulled = await scheduler.pull(batch_size=1)
        await scheduler.ack_start(pulled[0].ticket_id)
        result = TaskResult(
            result_id="r1", ticket_id=pulled[0].ticket_id, status=ResultStatus.SUCCESS
        )
        receipt = await scheduler.report_result(result)
        assert receipt.final_status == TicketStatus.COMPLETED
        assert not receipt.retried

    async def test_report_failure_retries(self, scheduler):
        await scheduler.submit_envelope(_envelope(1))
        pulled = await scheduler.pull(batch_size=1)
        await scheduler.ack_start(pulled[0].ticket_id)
        result = TaskResult(
            result_id="r1", ticket_id=pulled[0].ticket_id, status=ResultStatus.FAILED,
            error="timeout"
        )
        receipt = await scheduler.report_result(result)
        assert receipt.retried
        assert receipt.final_status == TicketStatus.QUEUED
        ticket = await scheduler.get_ticket(pulled[0].ticket_id)
        assert ticket.attempt_count == 1

    async def test_report_failure_exhausts_retries(self, scheduler):
        envelope = PlanEnvelope(
            envelope_id="e1", source_agent="test",
            tickets=[TaskTicket(ticket_id="t0", envelope_id="e1", max_attempts=1)]
        )
        await scheduler.submit_envelope(envelope)
        pulled = await scheduler.pull(batch_size=1)
        await scheduler.ack_start(pulled[0].ticket_id)
        result = TaskResult(result_id="r1", ticket_id="t0", status=ResultStatus.FAILED)
        receipt = await scheduler.report_result(result)
        assert receipt.final_status == TicketStatus.FAILED
        assert not receipt.retried

    async def test_report_expanded_spawns_tickets(self, scheduler):
        await scheduler.submit_envelope(_envelope(1))
        pulled = await scheduler.pull(batch_size=1)
        await scheduler.ack_start(pulled[0].ticket_id)
        result = TaskResult(
            result_id="r1", ticket_id=pulled[0].ticket_id, status=ResultStatus.EXPANDED,
            spawned_tickets=[
                {"ticket_id": "child1", "envelope_id": "e1", "payload": {"x": 1}},
                {"ticket_id": "child2", "envelope_id": "e1", "payload": {"x": 2}},
            ]
        )
        receipt = await scheduler.report_result(result)
        assert receipt.final_status == TicketStatus.EXPANDED
        assert receipt.spawned_count == 2
        child = await scheduler.get_ticket("child1")
        assert child is not None
        assert child.status == TicketStatus.QUEUED


class TestEnvelopeProgress:
    async def test_progress_counts(self, scheduler):
        await scheduler.submit_envelope(_envelope(3))
        progress = await scheduler.get_envelope_progress("e1")
        assert progress.total == 3
        assert progress.queued == 3
        assert progress.completed == 0


class TestCancel:
    async def test_cancel_ticket(self, scheduler):
        await scheduler.submit_envelope(_envelope(1))
        await scheduler.cancel_ticket("t0")
        ticket = await scheduler.get_ticket("t0")
        assert ticket.status == TicketStatus.CANCELLED

    async def test_cancel_envelope(self, scheduler):
        await scheduler.submit_envelope(_envelope(3))
        await scheduler.cancel_envelope("e1")
        progress = await scheduler.get_envelope_progress("e1")
        assert progress.cancelled == 3


class TestRelease:
    async def test_release_returns_to_queue(self, scheduler):
        await scheduler.submit_envelope(_envelope(1))
        pulled = await scheduler.pull(batch_size=1)
        await scheduler.release(pulled[0].ticket_id, reason="manual")
        ticket = await scheduler.get_ticket(pulled[0].ticket_id)
        assert ticket.status == TicketStatus.QUEUED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/taskplane/test_scheduler.py -v`
Expected: FAIL

- [ ] **Step 3: Implement TaskScheduler**

```python
# src/autospider/taskplane/scheduler.py
"""TaskScheduler — main entry point for the TaskPlane module."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .protocol import PlanEnvelope, TaskResult, TaskTicket, TicketStatus, ResultStatus
from .store.base import TaskStore
from .strategy import DispatchStrategy, PriorityStrategy
from .types import EnvelopeProgress, ReportReceipt, SubmitReceipt


class TaskScheduler:
    def __init__(
        self,
        store: TaskStore,
        *,
        dispatch_strategy: DispatchStrategy | None = None,
        on_ticket_complete: Callable[[TaskTicket, TaskResult], Awaitable[None]] | None = None,
        on_ticket_failed: Callable[[TaskTicket, str], Awaitable[None]] | None = None,
        on_envelope_complete: Callable[[PlanEnvelope], Awaitable[None]] | None = None,
    ) -> None:
        self._store = store
        self._strategy = dispatch_strategy or PriorityStrategy()
        self._on_ticket_complete = on_ticket_complete
        self._on_ticket_failed = on_ticket_failed
        self._on_envelope_complete = on_envelope_complete

    # ── Plan Agent API ──

    async def submit_envelope(self, envelope: PlanEnvelope) -> SubmitReceipt:
        await self._store.save_envelope(envelope)
        queued_tickets: list[TaskTicket] = []
        for ticket in envelope.tickets:
            queued = ticket.model_copy(update={"status": TicketStatus.QUEUED})
            queued_tickets.append(queued)
        await self._store.save_tickets_batch(queued_tickets)
        return SubmitReceipt(envelope_id=envelope.envelope_id, ticket_count=len(queued_tickets))

    async def submit_tickets(self, envelope_id: str, tickets: list[TaskTicket]) -> list[str]:
        queued: list[TaskTicket] = []
        ids: list[str] = []
        for ticket in tickets:
            t = ticket.model_copy(update={
                "envelope_id": envelope_id,
                "status": TicketStatus.QUEUED,
            })
            queued.append(t)
            ids.append(t.ticket_id)
        await self._store.save_tickets_batch(queued)
        return ids

    async def cancel_ticket(self, ticket_id: str, reason: str = "") -> None:
        ticket = await self._store.get_ticket(ticket_id)
        if ticket and not ticket.status.is_terminal:
            await self._store.update_status(ticket_id, TicketStatus.CANCELLED)

    async def cancel_envelope(self, envelope_id: str, reason: str = "") -> None:
        tickets = await self._store.get_tickets_by_envelope(envelope_id)
        for ticket in tickets:
            if not ticket.status.is_terminal:
                await self._store.update_status(ticket.ticket_id, TicketStatus.CANCELLED)

    # ── Execute Agent API (Pull) ──

    async def pull(
        self, *, labels: dict[str, str] | None = None, batch_size: int = 1
    ) -> list[TaskTicket]:
        return await self._store.claim_next(labels=labels, batch_size=batch_size)

    async def ack_start(self, ticket_id: str, agent_id: str = "") -> None:
        kwargs: dict[str, Any] = {}
        if agent_id:
            kwargs["assigned_to"] = agent_id
        await self._store.update_status(ticket_id, TicketStatus.RUNNING, **kwargs)

    async def report_result(self, result: TaskResult) -> ReportReceipt:
        await self._store.save_result(result)
        ticket = await self._store.get_ticket(result.ticket_id)
        if ticket is None:
            raise ValueError(f"unknown_ticket: {result.ticket_id}")

        if result.status == ResultStatus.SUCCESS:
            await self._store.update_status(result.ticket_id, TicketStatus.COMPLETED)
            if self._on_ticket_complete:
                updated = await self._store.get_ticket(result.ticket_id)
                await self._on_ticket_complete(updated, result)
            return ReportReceipt(
                ticket_id=result.ticket_id,
                final_status=TicketStatus.COMPLETED,
                retried=False,
                spawned_count=0,
            )

        if result.status == ResultStatus.EXPANDED:
            await self._store.update_status(result.ticket_id, TicketStatus.EXPANDED)
            spawned_tickets = [
                TaskTicket.model_validate({**raw, "envelope_id": ticket.envelope_id})
                for raw in result.spawned_tickets
            ]
            if spawned_tickets:
                await self.submit_tickets(ticket.envelope_id, spawned_tickets)
            return ReportReceipt(
                ticket_id=result.ticket_id,
                final_status=TicketStatus.EXPANDED,
                retried=False,
                spawned_count=len(spawned_tickets),
            )

        # ResultStatus.FAILED
        new_attempt = ticket.attempt_count + 1
        if new_attempt < ticket.max_attempts:
            await self._store.update_status(
                result.ticket_id, TicketStatus.QUEUED, attempt_count=new_attempt
            )
            return ReportReceipt(
                ticket_id=result.ticket_id,
                final_status=TicketStatus.QUEUED,
                retried=True,
                spawned_count=0,
            )

        await self._store.update_status(
            result.ticket_id, TicketStatus.FAILED, attempt_count=new_attempt
        )
        if self._on_ticket_failed:
            updated = await self._store.get_ticket(result.ticket_id)
            await self._on_ticket_failed(updated, result.error)
        return ReportReceipt(
            ticket_id=result.ticket_id,
            final_status=TicketStatus.FAILED,
            retried=False,
            spawned_count=0,
        )

    async def heartbeat(self, ticket_id: str) -> None:
        # MemoryStore: no-op. Redis store will extend claim TTL.
        pass

    async def release(self, ticket_id: str, reason: str = "") -> None:
        await self._store.release_claim(ticket_id, reason)

    # ── Query API ──

    async def get_envelope_progress(self, envelope_id: str) -> EnvelopeProgress:
        tickets = await self._store.get_tickets_by_envelope(envelope_id)
        counts: dict[str, int] = {}
        for ticket in tickets:
            counts[ticket.status.value] = counts.get(ticket.status.value, 0) + 1
        return EnvelopeProgress(
            envelope_id=envelope_id,
            total=len(tickets),
            queued=counts.get("queued", 0),
            dispatched=counts.get("dispatched", 0),
            running=counts.get("running", 0),
            completed=counts.get("completed", 0),
            failed=counts.get("failed", 0),
            expanded=counts.get("expanded", 0),
            cancelled=counts.get("cancelled", 0),
        )

    async def get_ticket(self, ticket_id: str) -> TaskTicket | None:
        return await self._store.get_ticket(ticket_id)

    async def get_result(self, ticket_id: str) -> TaskResult | None:
        return await self._store.get_result(ticket_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/taskplane/test_scheduler.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```
git add -f src/autospider/taskplane/scheduler.py tests/unit/taskplane/test_scheduler.py
git commit -m "feat(taskplane): add TaskScheduler with submit/pull/report/cancel/progress"
```

---

### Task 7: Subscription (Push mode)

**Files:**
- Create: `src/autospider/taskplane/subscription.py`
- Test: `tests/unit/taskplane/test_subscription.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/taskplane/test_subscription.py
import asyncio
import pytest
from autospider.taskplane.protocol import (
    PlanEnvelope, TaskTicket, TaskResult, ResultStatus,
)
from autospider.taskplane.scheduler import TaskScheduler
from autospider.taskplane.store.memory_store import MemoryStore
from autospider.taskplane.subscription import Subscription


@pytest.fixture
def scheduler():
    return TaskScheduler(store=MemoryStore())


class TestSubscription:
    async def test_processes_all_tickets(self, scheduler):
        tickets = [TaskTicket(ticket_id=f"t{i}", envelope_id="e1") for i in range(3)]
        envelope = PlanEnvelope(envelope_id="e1", source_agent="test", tickets=tickets)
        await scheduler.submit_envelope(envelope)

        processed = []

        async def handler(ticket: TaskTicket) -> TaskResult:
            processed.append(ticket.ticket_id)
            return TaskResult(
                result_id=f"r-{ticket.ticket_id}",
                ticket_id=ticket.ticket_id,
                status=ResultStatus.SUCCESS,
            )

        sub = Subscription(scheduler=scheduler, handler=handler, concurrency=2, poll_interval=0.05)
        await sub.start()
        # Give it time to process
        await asyncio.sleep(0.5)
        await sub.stop()

        assert len(processed) == 3

    async def test_stops_gracefully(self, scheduler):
        sub = Subscription(
            scheduler=scheduler,
            handler=lambda t: TaskResult(result_id="r", ticket_id=t.ticket_id, status=ResultStatus.SUCCESS),
            concurrency=1,
            poll_interval=0.05,
        )
        await sub.start()
        await asyncio.sleep(0.1)
        await sub.stop()
        # Should not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/taskplane/test_subscription.py -v`
Expected: FAIL

- [ ] **Step 3: Implement Subscription**

```python
# src/autospider/taskplane/subscription.py
"""Push-mode subscription: wraps pull loop + worker pool."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from .protocol import TaskResult, TaskTicket
from .scheduler import TaskScheduler


class Subscription:
    def __init__(
        self,
        *,
        scheduler: TaskScheduler,
        handler: Callable[[TaskTicket], Awaitable[TaskResult]],
        labels: dict[str, str] | None = None,
        concurrency: int = 1,
        poll_interval: float = 1.0,
    ) -> None:
        self._scheduler = scheduler
        self._handler = handler
        self._labels = labels
        self._concurrency = max(1, concurrency)
        self._poll_interval = poll_interval
        self._running = False
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        self._running = True
        for i in range(self._concurrency):
            task = asyncio.create_task(self._worker_loop(i))
            self._tasks.append(task)

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _worker_loop(self, worker_id: int) -> None:
        while self._running:
            pulled = await self._scheduler.pull(labels=self._labels, batch_size=1)
            if not pulled:
                await asyncio.sleep(self._poll_interval)
                continue
            ticket = pulled[0]
            await self._scheduler.ack_start(ticket.ticket_id, agent_id=f"sub-worker-{worker_id}")
            try:
                result = await self._handler(ticket)
                await self._scheduler.report_result(result)
            except Exception as exc:
                error_result = TaskResult(
                    result_id=f"error-{ticket.ticket_id}",
                    ticket_id=ticket.ticket_id,
                    status=ResultStatus.FAILED,
                    error=str(exc)[:500],
                )
                await self._scheduler.report_result(error_result)


# Needed for error_result construction
from .protocol import ResultStatus
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/taskplane/test_subscription.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
git add -f src/autospider/taskplane/subscription.py tests/unit/taskplane/test_subscription.py
git commit -m "feat(taskplane): add Subscription push-mode wrapper"
```

---

### Task 8: Module Public API (__init__.py)

**Files:**
- Modify: `src/autospider/taskplane/__init__.py`

- [ ] **Step 1: Update __init__.py with public exports**

```python
# src/autospider/taskplane/__init__.py
"""TaskPlane — 通用任务调度控制平面。"""

from .protocol import PlanEnvelope, TaskTicket, TaskResult, TicketStatus, ResultStatus
from .types import SubmitReceipt, ReportReceipt, EnvelopeProgress, TaskPlaneConfig
from .strategy import DispatchStrategy, FIFOStrategy, PriorityStrategy, BatchAwareStrategy
from .scheduler import TaskScheduler
from .subscription import Subscription
from .store import TaskStore, MemoryStore

__all__ = [
    "PlanEnvelope", "TaskTicket", "TaskResult", "TicketStatus", "ResultStatus",
    "SubmitReceipt", "ReportReceipt", "EnvelopeProgress", "TaskPlaneConfig",
    "DispatchStrategy", "FIFOStrategy", "PriorityStrategy", "BatchAwareStrategy",
    "TaskScheduler", "Subscription",
    "TaskStore", "MemoryStore",
]
```

- [ ] **Step 2: Verify all imports work**

Run: `python -c "from autospider.taskplane import TaskScheduler, MemoryStore, PlanEnvelope; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/unit/taskplane/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```
git add -f src/autospider/taskplane/__init__.py
git commit -m "feat(taskplane): finalize public API exports"
```

---

### Task 9: Adapter — PlanBridge

**Files:**
- Create: `src/autospider/taskplane_adapter/__init__.py`
- Create: `src/autospider/taskplane_adapter/plan_bridge.py`
- Test: `tests/unit/taskplane_adapter/test_plan_bridge.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/taskplane_adapter/test_plan_bridge.py
import pytest
from autospider.domain.planning import TaskPlan, SubTask
from autospider.taskplane.protocol import PlanEnvelope
from autospider.taskplane_adapter.plan_bridge import PlanBridge


def _sample_plan() -> TaskPlan:
    return TaskPlan(
        plan_id="plan-001",
        original_request="采集招标公告",
        site_url="https://example.com",
        subtasks=[
            SubTask(id="s1", name="招标公告", list_url="https://example.com/zb", task_description="采集招标公告列表"),
            SubTask(id="s2", name="中标公告", list_url="https://example.com/zb2", task_description="采集中标公告列表"),
        ],
        shared_fields=[{"name": "title", "description": "标题"}],
    )


class TestPlanBridge:
    def test_to_envelope(self):
        plan = _sample_plan()
        envelope = PlanBridge.to_envelope(plan, source_agent="plan_node")
        assert envelope.envelope_id == "plan-001"
        assert envelope.source_agent == "plan_node"
        assert len(envelope.tickets) == 2
        assert envelope.tickets[0].ticket_id == "s1"
        assert envelope.plan_snapshot["original_request"] == "采集招标公告"

    def test_from_envelope(self):
        plan = _sample_plan()
        envelope = PlanBridge.to_envelope(plan)
        restored = PlanBridge.from_envelope(envelope)
        assert restored.plan_id == "plan-001"
        assert len(restored.subtasks) == 2

    def test_roundtrip(self):
        plan = _sample_plan()
        envelope = PlanBridge.to_envelope(plan)
        restored = PlanBridge.from_envelope(envelope)
        assert restored.original_request == plan.original_request
        assert restored.site_url == plan.site_url
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/taskplane_adapter/test_plan_bridge.py -v`
Expected: FAIL

- [ ] **Step 3: Implement PlanBridge**

```python
# src/autospider/taskplane_adapter/__init__.py
"""Autospider-specific adapters for TaskPlane."""

# src/autospider/taskplane_adapter/plan_bridge.py
"""Convert TaskPlan ↔ PlanEnvelope."""

from __future__ import annotations

from typing import Any

from ..domain.planning import TaskPlan
from ..taskplane.protocol import PlanEnvelope, TaskTicket
from .subtask_bridge import SubtaskBridge


class PlanBridge:
    @staticmethod
    def to_envelope(
        plan: TaskPlan,
        *,
        source_agent: str = "plan_node",
        request_params: dict[str, Any] | None = None,
    ) -> PlanEnvelope:
        tickets = [
            SubtaskBridge.to_ticket(subtask, envelope_id=plan.plan_id)
            for subtask in plan.subtasks
        ]
        return PlanEnvelope(
            envelope_id=plan.plan_id,
            source_agent=source_agent,
            metadata={
                "original_request": plan.original_request,
                "site_url": plan.site_url,
                "shared_fields": list(plan.shared_fields or []),
                **(dict(request_params or {})),
            },
            tickets=tickets,
            plan_snapshot=plan.model_dump(mode="python"),
        )

    @staticmethod
    def from_envelope(envelope: PlanEnvelope) -> TaskPlan:
        return TaskPlan.model_validate(envelope.plan_snapshot)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/taskplane_adapter/test_plan_bridge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
git add -f src/autospider/taskplane_adapter/ tests/unit/taskplane_adapter/
git commit -m "feat(taskplane-adapter): add PlanBridge for TaskPlan ↔ PlanEnvelope"
```

---

### Task 10: Adapter — SubtaskBridge

**Files:**
- Create: `src/autospider/taskplane_adapter/subtask_bridge.py`
- Test: `tests/unit/taskplane_adapter/test_subtask_bridge.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/taskplane_adapter/test_subtask_bridge.py
from autospider.domain.planning import SubTask
from autospider.taskplane.protocol import TaskTicket
from autospider.taskplane_adapter.subtask_bridge import SubtaskBridge


def _sample_subtask() -> SubTask:
    return SubTask(
        id="s1",
        name="招标公告",
        list_url="https://example.com/zb",
        task_description="采集招标公告列表",
        priority=2,
        depth=1,
    )


class TestSubtaskBridge:
    def test_to_ticket(self):
        subtask = _sample_subtask()
        ticket = SubtaskBridge.to_ticket(subtask, envelope_id="e1")
        assert ticket.ticket_id == "s1"
        assert ticket.envelope_id == "e1"
        assert ticket.priority == 2
        assert ticket.labels["depth"] == "1"
        assert ticket.payload["list_url"] == "https://example.com/zb"

    def test_from_ticket(self):
        subtask = _sample_subtask()
        ticket = SubtaskBridge.to_ticket(subtask, envelope_id="e1")
        restored = SubtaskBridge.from_ticket(ticket)
        assert restored.id == "s1"
        assert restored.name == "招标公告"
        assert restored.list_url == "https://example.com/zb"

    def test_roundtrip(self):
        subtask = _sample_subtask()
        ticket = SubtaskBridge.to_ticket(subtask, envelope_id="e1")
        restored = SubtaskBridge.from_ticket(ticket)
        assert restored.task_description == subtask.task_description
        assert restored.priority == subtask.priority
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/taskplane_adapter/test_subtask_bridge.py -v`
Expected: FAIL

- [ ] **Step 3: Implement SubtaskBridge**

```python
# src/autospider/taskplane_adapter/subtask_bridge.py
"""Convert SubTask ↔ TaskTicket."""

from __future__ import annotations

from ..domain.planning import SubTask
from ..taskplane.protocol import TaskTicket


class SubtaskBridge:
    @staticmethod
    def to_ticket(subtask: SubTask, *, envelope_id: str) -> TaskTicket:
        labels: dict[str, str] = {
            "mode": subtask.mode.value,
            "depth": str(subtask.depth),
        }
        scope = dict(subtask.scope or {})
        if scope.get("key"):
            labels["scope_key"] = str(scope["key"])
        return TaskTicket(
            ticket_id=subtask.id,
            envelope_id=envelope_id,
            parent_ticket_id=subtask.parent_id,
            priority=subtask.priority,
            payload=subtask.model_dump(mode="python"),
            labels=labels,
        )

    @staticmethod
    def from_ticket(ticket: TaskTicket) -> SubTask:
        return SubTask.model_validate(ticket.payload)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/taskplane_adapter/test_subtask_bridge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
git add -f src/autospider/taskplane_adapter/subtask_bridge.py tests/unit/taskplane_adapter/test_subtask_bridge.py
git commit -m "feat(taskplane-adapter): add SubtaskBridge for SubTask ↔ TaskTicket"
```

---

### Task 11: Adapter — ResultBridge

**Files:**
- Create: `src/autospider/taskplane_adapter/result_bridge.py`
- Test: `tests/unit/taskplane_adapter/test_result_bridge.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/taskplane_adapter/test_result_bridge.py
from autospider.domain.runtime import SubTaskRuntimeState
from autospider.taskplane.protocol import TaskResult, ResultStatus
from autospider.taskplane_adapter.result_bridge import ResultBridge


def _sample_runtime_state() -> SubTaskRuntimeState:
    return SubTaskRuntimeState(
        subtask_id="s1",
        name="招标公告",
        status="completed",
        outcome_type="success",
        collected_count=42,
        result_file="output/items.jsonl",
    )


class TestResultBridge:
    def test_to_result_success(self):
        state = _sample_runtime_state()
        result = ResultBridge.to_result(state)
        assert result.ticket_id == "s1"
        assert result.status == ResultStatus.SUCCESS
        assert result.output["collected_count"] == 42

    def test_to_result_failed(self):
        state = SubTaskRuntimeState(
            subtask_id="s1", status="system_failure", outcome_type="system_failure", error="timeout"
        )
        result = ResultBridge.to_result(state)
        assert result.status == ResultStatus.FAILED
        assert result.error == "timeout"

    def test_to_result_expanded(self):
        state = SubTaskRuntimeState(
            subtask_id="s1", status="expanded", outcome_type="expanded",
            expand_request={"spawned_subtasks": [{"id": "child1"}]},
        )
        result = ResultBridge.to_result(state)
        assert result.status == ResultStatus.EXPANDED

    def test_from_result(self):
        result = TaskResult(
            result_id="r1", ticket_id="s1", status=ResultStatus.SUCCESS,
            output={"subtask_id": "s1", "name": "test", "status": "completed", "collected_count": 10},
        )
        state = ResultBridge.from_result(result)
        assert state.subtask_id == "s1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/taskplane_adapter/test_result_bridge.py -v`
Expected: FAIL

- [ ] **Step 3: Implement ResultBridge**

```python
# src/autospider/taskplane_adapter/result_bridge.py
"""Convert SubTaskRuntimeState ↔ TaskResult."""

from __future__ import annotations

import uuid
from typing import Any

from ..domain.runtime import SubTaskRuntimeState
from ..taskplane.protocol import ResultStatus, TaskResult

_STATUS_MAP: dict[str, ResultStatus] = {
    "completed": ResultStatus.SUCCESS,
    "success": ResultStatus.SUCCESS,
    "expanded": ResultStatus.EXPANDED,
    "system_failure": ResultStatus.FAILED,
    "business_failure": ResultStatus.FAILED,
    "no_data": ResultStatus.FAILED,
}


class ResultBridge:
    @staticmethod
    def to_result(state: SubTaskRuntimeState) -> TaskResult:
        outcome = str(state.outcome_type or state.status or "").strip().lower()
        result_status = _STATUS_MAP.get(outcome, ResultStatus.FAILED)
        artifacts: list[dict[str, str]] = []
        if state.result_file:
            artifacts.append({"label": "result_file", "path": state.result_file})
        spawned: list[dict[str, Any]] = []
        if state.expand_request:
            spawned = list(state.expand_request.get("spawned_subtasks") or [])
        return TaskResult(
            result_id=str(uuid.uuid4()),
            ticket_id=state.subtask_id,
            status=result_status,
            output=state.model_dump(mode="python"),
            error=state.error or "",
            artifacts=artifacts,
            spawned_tickets=spawned,
        )

    @staticmethod
    def from_result(result: TaskResult) -> SubTaskRuntimeState:
        return SubTaskRuntimeState.model_validate(result.output)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/taskplane_adapter/test_result_bridge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
git add -f src/autospider/taskplane_adapter/result_bridge.py tests/unit/taskplane_adapter/test_result_bridge.py
git commit -m "feat(taskplane-adapter): add ResultBridge for SubTaskRuntimeState ↔ TaskResult"
```

---

### Task 12: Add pytest marker and run full smoke suite

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add `integration` marker to pytest config**

In `pyproject.toml`, add to `markers`:
```
"integration: integration tests requiring Redis/PG",
```

- [ ] **Step 2: Run full smoke tests**

Run: `pytest tests/unit/taskplane/ tests/unit/taskplane_adapter/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```
git add pyproject.toml
git commit -m "chore: add integration pytest marker for taskplane"
```

---

### Task 13: RedisHotStore (deferred — requires Redis)

> This task is intentionally deferred. Implement after Tasks 1-12 are verified working. The `MemoryStore` provides full functionality for development and testing.

**Files:**
- Create: `src/autospider/taskplane/store/redis_store.py`
- Test: `tests/integration/taskplane/test_redis_store.py`

Implementation follows the Redis data structure mapping defined in the design spec (Section 4.2). All tests should be marked `@pytest.mark.integration`.

---

### Task 14: PgColdStore (deferred — requires PG)

> This task is intentionally deferred. Implement after Tasks 1-12 are verified working.

**Files:**
- Create: `src/autospider/taskplane/store/pg_store.py`
- Test: `tests/integration/taskplane/test_pg_store.py`

Implementation uses SQLAlchemy 2.x async with the table schema from the design spec (Section 4.3). All tests should be marked `@pytest.mark.integration`.

---

### Task 15: DualLayerStore (deferred — requires Redis + PG)

> This task is intentionally deferred. Implement after Tasks 13 and 14.

**Files:**
- Create: `src/autospider/taskplane/store/dual_store.py`
- Test: `tests/integration/taskplane/test_dual_store.py`

Implementation follows the sync strategy table from the design spec (Section 4.4).
