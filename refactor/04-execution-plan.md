# 04 · 执行计划（commit 级）

按 5 个阶段、~25 个 local commit 推进。**每个 commit 必须自包含、测试绿、diff ≤ 800 行**；每阶段末打 tag 便于 `git reset --hard <tag>` 回滚；**全程不 `git push`**。

---

## 0. 前置约定

### 0.1 通用规则

- **Commit 消息**：Conventional Commits（`feat: / refactor: / chore: / test: / docs: / fix: / build:`），scope 用层级或 Context 名：
  - `feat(platform-messaging): ...`
  - `refactor(contexts-planning): move domain models`
  - `chore(infra): drop legacy common package`
- **diff 上限**：单 commit ≤ 800 行新增+删除。超出必须继续拆。仅"搬家"可放宽到 1500 行（纯 `git mv` + import 重写）。
- **每个 commit 前**：
  ```powershell
  scripts/verify.ps1
  ```
- **每个 commit 完成**：打本地 tag（阶段最后一个 commit 打 `refactor-phase-<n>`）。
- **回滚**：
  ```powershell
  git reset --hard refactor-phase-<n>
  ```

### 0.2 `scripts/verify.ps1`（commit[0.2] 创建，后续所有阶段都用）

等价于：

```powershell
ruff check src tests
black --check src tests
mypy src/autospider
pytest -m smoke -q
pytest tests/contracts -q
lint-imports             # 阶段 5 之后才启用，之前跳过
```

---

## 阶段 0 · 契约快照安全网

**目标**：在不改业务代码的前提下，用快照记录"现状"，后续大改才能看出差异。

### commit[0.1] · 契约快照测试

**新增文件**（仅在 `tests/contracts/` 下）：

- `tests/contracts/__init__.py`
- `tests/contracts/test_cli_surface.py`
  - 用 `typer.testing.CliRunner` 调 `autospider --help`、`autospider chat-pipeline --help`、`autospider resume --help`、`autospider doctor --help`、`autospider benchmark --help`
  - 对输出做 `syrupy` 或 inline 快照断言
- `tests/contracts/test_redis_keys_surface.py`
  - 用 `fakeredis` 跑一次最小化 pipeline（mock LLM + 本地 HTTP 静态页）
  - 断言执行结束后 Redis 中出现的 key prefix 集合、每个 prefix 下的 payload shape（字段名而非值）
- `tests/contracts/test_output_layout.py`
  - 跑最小 pipeline 后断言 `output/` 下的目录树与 JSON schema（用 `jsonschema` 库）
- `tests/contracts/test_result_envelope.py`
  - 对目前"任意可用"的用例返回做 shape 快照，作为后续 `ResultEnvelope` 迁移的对照

**验证**：`pytest tests/contracts -q` 全绿。

**Commit 消息**：`test(contracts): add cli/redis/output/result snapshots as refactor safety net`

### commit[0.2] · 本地验证脚本 + pre-commit 雏形

**新增文件**：
- `scripts/verify.ps1`（内容见 §0.2）
- `scripts/verify.sh`（Linux/macOS 等价版，便于未来跨平台）
- 在 `pyproject.toml` 的 `[project.optional-dependencies].dev` 中新增：`import-linter>=2.0`、`syrupy>=4.0`、`jsonschema>=4.0`、`fakeredis>=2.20`、`pre-commit>=3.5`、`vulture>=2.10`、`deptry>=0.12`

**注意**：`scripts/` 在 `.gitignore` 中被忽略，需要先编辑 `.gitignore`，把 `scripts/` 这行删掉或改为 `scripts/output/` 之类的更精确模式。本 commit **同时修改 `.gitignore`**：

```diff
- scripts/
+ scripts/_generated/
```

**验证**：`scripts/verify.ps1` 跑通（此时 `import-linter` 尚无配置，跳过）。

**Commit 消息**：`chore(dev): add verify script and enable scripts/ to be tracked`

**打 tag**：`git tag refactor-phase-0`

---

## 阶段 1 · 骨架 + 新 DB + Redis registry + 日志基建

**目标**：搭好新架构的空骨架，重设计 DB schema 与 Redis key 规范，落地统一的日志与 contextvars。**此阶段不动任何旧业务代码**，新老并存。

### commit[1.1] · 空骨架 + Shared Kernel

**新增目录与文件**（全部 `__init__.py` + 单行文档字符串）：

```
src/autospider/contexts/__init__.py
src/autospider/contexts/planning/{__init__.py, domain/__init__.py, application/__init__.py, infrastructure/__init__.py}
src/autospider/contexts/collection/{__init__.py, domain/__init__.py, application/__init__.py, infrastructure/__init__.py}
src/autospider/contexts/experience/{__init__.py, domain/__init__.py, application/__init__.py, infrastructure/__init__.py}
src/autospider/contexts/chat/{__init__.py, domain/__init__.py, application/__init__.py, infrastructure/__init__.py}
src/autospider/composition/{__init__.py, graph/__init__.py, sagas/__init__.py, use_cases/__init__.py}
src/autospider/platform/{__init__.py, shared_kernel/__init__.py, browser/__init__.py, llm/__init__.py, messaging/__init__.py, persistence/__init__.py, observability/__init__.py, config/__init__.py}
src/autospider/platform/persistence/{redis/__init__.py, sql/__init__.py, files/__init__.py}
src/autospider/interface/__init__.py
src/autospider/interface/cli/__init__.py
```

**Shared Kernel 内容**：
- `platform/shared_kernel/ids.py` — 定义 `RunId`、`TaskId`、`SubTaskId`、`PlanId`、`SkillId`（`typing.NewType`）
- `platform/shared_kernel/time.py` — `UtcDatetime` alias + `Clock` Protocol + `SystemClock`
- `platform/shared_kernel/errors.py` — `DomainError`、`InfrastructureError`
- `platform/shared_kernel/result.py` — `ResultEnvelope[T]`、`ErrorInfo`（按 `03-contracts.md §5`）
- `platform/shared_kernel/trace.py` — `contextvars` 定义与访问器（`set_run_context` / `clear_run_context` / `get_run_id` / `get_trace_id`）

**测试**：
- `tests/platform/shared_kernel/test_result.py`（覆盖成功/失败/部分）
- `tests/platform/shared_kernel/test_trace.py`（contextvar 隔离）

**Commit 消息**：`feat(platform): scaffold ddd skeleton and shared kernel (ids, result, errors, trace)`

### commit[1.2] · Observability 基建

**新增**：
- `platform/observability/logging.py` — loguru sink 配置 + patcher 注入 `run_id`/`trace_id`
- `platform/observability/log_schema.py` — 统一字段常量、事件命名前缀
- `platform/observability/metrics.py` — 计数器/耗时的简单记录
- `platform/config/settings.py` — pydantic-settings 从 `.env` 加载（仅日志相关字段，其他后续追加）

**测试**：
- `tests/platform/observability/test_logging.py`（断言日志输出包含 `run_id` / `trace_id`）

**Commit 消息**：`feat(platform-observability): structured logging with run_id/trace_id contextvars`

### commit[1.3] · 新 DB Schema + Alembic

**新增**：
- `src/autospider/platform/persistence/sql/engine.py` — SQLAlchemy engine/session
- `src/autospider/platform/persistence/sql/alembic/env.py` 等 alembic 模板
- `src/autospider/platform/persistence/sql/alembic/versions/0001_init.py`  — 按 `03-contracts.md §1.2` 创建所有 Context 表
- `alembic.ini`（项目根）

**注意**：旧 `common/db/models.py` **暂不删除**，但新 alembic **不加载它**（两套完全隔离）。旧代码继续用旧表，新架构搭好后一次性切换。

**验证**：
- `alembic upgrade head` 在空库上成功建表
- `tests/platform/persistence/sql/test_migration.py` 用 SQLite in-memory 验证迁移可跑

**Commit 消息**：`feat(platform-persistence): new db schema with alembic initial migration`

### commit[1.4] · Redis 连接与 key registry

**新增**：
- `platform/persistence/redis/connection.py` — 连接池封装（基于 `redis.asyncio`）
- `platform/persistence/redis/keys.py` — 按 `03-contracts.md §2.2` 的全部 key 函数
- `platform/persistence/redis/base_repository.py` — 通用操作封装（Hash/Set/List 辅助方法）

**测试**：
- `tests/platform/persistence/redis/test_keys.py`（断言每个 key 函数生成的字符串符合规范）
- `tests/platform/persistence/redis/test_base_repository.py`（用 `fakeredis` 测 CRUD）

**Commit 消息**：`feat(platform-persistence): redis connection pool and centralized key registry`

### commit[1.5] · Messaging 抽象 + 两实现

**新增**：
- `platform/messaging/ports.py` — `Event` / `Messaging` Protocol（按 `03-contracts.md §3.1`）
- `platform/messaging/redis_streams.py` — 基于 Redis Streams 的实现（包含 Lua 脚本 push/fetch/fail；可参考旧 `common/storage/redis_manager.py` 中的 Lua，但重写为干净版）
- `platform/messaging/in_memory.py` — 进程内实现（测试用，带 Consumer Group 语义模拟）

**测试**：
- `tests/platform/messaging/test_in_memory.py` — 发布/订阅/ack/fail/重试
- `tests/platform/messaging/test_redis_streams.py` — 用 `fakeredis` 跑上述场景

**Commit 消息**：`feat(platform-messaging): event/messaging protocol with redis-streams and in-memory impls`

**打 tag**：`git tag refactor-phase-1`

---

## 阶段 2 · Bounded Context 迁入（按依赖从少到多）

**顺序**：Chat → Experience → Planning → Collection。每个 Context 用相同 5-commit 模板。

### 2.A · Chat Context

#### commit[2.1.1] · chat/domain
- `git mv src/autospider/domain/chat.py src/autospider/contexts/chat/domain/model.py`（随后编辑 import）
- 在 `contexts/chat/domain/` 新增 `ports.py`（`SessionRepository`、`LLMClarifier` Protocol）、`events.py`（`TaskClarified` 事件）
- 迁移 `common/llm/task_clarifier.py` 中的**领域规则**到 `domain/services.py`（如意图归一化算法），外部调用部分留到 application/infra
- 旧 `autospider.domain.chat` 的所有引用改为 `autospider.contexts.chat.domain.model`（用 `grep -r` 后批量改）

**验证**：`scripts/verify.ps1` 绿

#### commit[2.1.2] · chat/application
- `contexts/chat/application/use_cases/start_clarification.py`
- `contexts/chat/application/use_cases/advance_dialogue.py`
- `contexts/chat/application/use_cases/finalize_task.py`
- `contexts/chat/application/dto.py`
- 原 `common/llm/task_clarifier.py` 的协调逻辑迁入 use cases

#### commit[2.1.3] · chat/infrastructure
- `contexts/chat/infrastructure/repositories/session_repository.py` — 用 Redis Hash 存 `ch_sessions`（同时可考虑 SQL 备份，本阶段先用 Redis）
- `contexts/chat/infrastructure/adapters/llm_clarifier.py` — 调 `platform.llm`

#### commit[2.1.4] · chat 接线 + 测试
- 更新 `composition/container.py`（本阶段先写桩，完整的 container 在阶段 3）
- `tests/contexts/chat/domain/` + `tests/contexts/chat/application/`

#### commit[2.1.5] · 删除旧 chat 路径
- 删除 `src/autospider/domain/chat.py`（已被空）
- 检查 `common/llm/task_clarifier.py` 是否还被其他模块使用；如无则删
- 更新 `src/autospider/domain/__init__.py` 去掉 chat 的 re-export

**验证**：`scripts/verify.ps1` 绿 + `ruff --select F401` 无新增未用 import

### 2.B · Experience Context（commit[2.2.1]~[2.2.5]）

按同模板：
1. 拆 `common/experience/skill_sedimenter.py` 的纯算法 → `contexts/experience/domain/services.py` + `policies.py`
2. 拆 use cases：`sediment_skill.py`、`lookup_skill.py`、`update_skill_stats.py`、`merge_skills.py`
3. `common/experience/skill_store.py` → `contexts/experience/infrastructure/repositories/`（按 `02-migration-map.md §2.4` 4 文件）
4. 接线 + 订阅 `collection.CollectionFinalized` 的 handler
5. 删除 `common/experience/`

**本阶段额外**：迁移时顺便拆分 `skill_sedimenter.py`（1050L）与 `skill_store.py`（1014L）两个巨石。

### 2.C · Planning Context（commit[2.3.1]~[2.3.5]）

按同模板：
1. `crawler/planner/planner_state.py` + `domain/planning.py` → `contexts/planning/domain/model.py`
2. `crawler/planner/task_planner.py` 的 **algorithm** → `domain/services.py` + `policies.py`（见 `02-migration-map.md §2.6`）
3. `crawler/planner/task_planner.py` 的 **coordination** → `application/use_cases/*`（4 个用例文件）
4. `crawler/planner/planner_artifacts.py` → `infrastructure/repositories/`；`planner_analysis_postprocess.py` → `application/use_cases/analyze_plan_result.py`
5. 接线 + 订阅 `chat.TaskClarified` 与 `collection.SubTaskFailed` 的 handlers；删除旧 `crawler/planner/`

**本阶段额外**：拆分 `task_planner.py`（973L）、`graph/failures.py` 进 `domain/policies.py`。

### 2.D · Collection Context（commit[2.4.1]~[2.4.7]，最复杂，多 2 个 commit）

1. **commit[2.4.1] domain models**：
   - `crawler/collector/models.py` + `field/models.py` + `domain/fields.py` + `pipeline/subtask_runtime.py` → `contexts/collection/domain/model.py`
   - `field/xpath_pattern.py`（1292L）拆分为 `domain/field/xpath/` 下 6 个文件（见 `02-migration-map.md §2.1`）**独立一个 commit 专门做这件事**
2. **commit[2.4.2] xpath_pattern 拆分**（独立 commit）
3. **commit[2.4.3] domain services/policies**：
   - `crawler/collector/navigation_handler.py` / `pagination_handler.py` 的策略部分 → `domain/services.py`
   - `crawler/planner/planner_variant_resolver.py` → `domain/policies.py`
   - `graph/world_model.py` → `domain/services.py`
   - `common/grouping_semantics.py`、`common/utils/fuzzy_search.py` → `domain/field/`
4. **commit[2.4.4] application/use_cases**：
   - `run_subtask.py`（合并 `pipeline/runner.py` + `pipeline/worker.py` + `crawler/base/base_collector.py`）
   - `navigate.py`、`paginate.py`、`extract_urls.py`、`extract_fields.py`、`extract_fields_batch.py`、`collect_urls.py`、`explore_site.py`、`finalize_run.py`、`generate_script.py`
5. **commit[2.4.5] field_extractor 拆分**（独立 commit，`field/field_extractor.py` 1150L → 4 文件）
6. **commit[2.4.6] infrastructure**：
   - `contexts/collection/infrastructure/repositories/` — run / page_result / field_xpath / progress
   - `contexts/collection/infrastructure/adapters/` — playwright_session / llm_field_decider / llm_navigator / scrapy_generator
   - 从 `common/storage/collection_persistence.py`、`field_xpath_*.py`、`crawler/collector/llm_decision.py`、`crawler/output/script_generator.py` 搬运
7. **commit[2.4.7] 接线 + 删除旧包**：
   - 订阅 `planning.SubTaskPlanned`、`queue.subtask` 的 worker
   - 发布 `collection.*` 事件
   - 删除 `crawler/`、`field/`、`pipeline/subtask_runtime.py`

**验证**：每个 commit 后 smoke + contracts 全绿；阶段末做一次 `pytest -m e2e` 的小集合冒烟（mock LLM）。

**打 tag**：`git tag refactor-phase-2`

---

## 阶段 3 · Composition 层与消息队列落地

### commit[3.1] · Messaging 端到端接入

- 在 `composition/container.py` 统一注入 `Messaging` 实现（生产：`RedisStreamsMessaging`；测试：`InMemoryMessaging`）
- 所有 Context 的 `infrastructure/publishers.py` 通过 `Messaging` 发事件
- 所有 Context 的 `application/handlers.py` 在 `composition/container.py` 中启动订阅循环

**测试**：
- `tests/composition/test_container.py`（验证 wiring 完整）
- `tests/composition/test_event_propagation.py`（端到端：发一个 `chat.TaskClarified` → 观察 Planning 接住）

**Commit 消息**：`feat(composition): wire messaging end-to-end with container DI`

### commit[3.2] · Saga 落地

- `composition/sagas/collection_saga.py`（替代 `pipeline/orchestration.py` + `pipeline/finalization.py` 的跨 Context 部分）
- `composition/sagas/recovery_saga.py`（替代 `graph/recovery.py`）
- `composition/sagas/multi_dispatch_saga.py`（替代 `graph/subgraphs/multi_dispatch.py`）

**测试**：
- `tests/composition/sagas/test_collection_saga.py`（In-memory messaging 下的状态流转）
- `tests/composition/sagas/test_recovery_saga.py`

**Commit 消息**：`feat(composition-sagas): collection/recovery/multi-dispatch sagas replace legacy orchestration`

### commit[3.3] · LangGraph 主图重写

- `composition/graph/main_graph.py`（薄包装版，仅调 use cases）
- `composition/graph/nodes/`（4 个文件，按 `02-migration-map.md §2.10`）
- `composition/graph/state.py`（合并 `graph/state.py` + `state_access.py` + `workflow_*.py`）
- `composition/graph/checkpoint.py`、`decision_context.py`、`handoff.py`、`controls.py`
- `composition/use_cases/run_chat_pipeline.py`、`resume.py`、`run_benchmark.py`（替代 `graph/runner.py` + `pipeline/runner.py` 的 CLI 入口部分）
- 重写 `interface/cli/`：`chat_pipeline.py`、`resume.py`、`doctor.py`、`benchmark.py`、`redis_ops.py`、`_rendering.py`、`__init__.py`（按 `02-migration-map.md §2.5`）
- `src/autospider/__main__.py` 与 `pyproject.toml` 的 `[project.scripts]` 指向 `interface.cli:main`

**测试**：
- `tests/composition/graph/` 所有节点的薄包装单测
- `tests/interface/cli/` 每个子命令冒烟
- 运行 `tests/contracts/test_cli_surface.py` 快照——**此时快照应当与阶段 0 拍摄时完全一致**（接口不变）

**Commit 消息**：`refactor(composition): rewrite langgraph main graph as thin use-case wrappers; new cli entrypoints`

**打 tag**：`git tag refactor-phase-3`

---

## 阶段 4 · 物理删除旧包 + 死代码扫除

### commit[4.1] · 大删除

**删除**（用 `git rm -r`）：
```
src/autospider/common/
src/autospider/crawler/
src/autospider/pipeline/
src/autospider/graph/
src/autospider/field/
src/autospider/domain/
src/autospider/taskplane/
src/autospider/taskplane_adapter/
src/autospider/cli.py
src/autospider/cli_runtime.py
src/autospider/artifacts/        （空目录）
src/autospider/output/           （空目录）
check_elements.py                （项目根的临时调试脚本）
tests/autospider_next/           （空目录）
tests/unit/                      （空目录）
```

**验证**：
- `scripts/verify.ps1` 绿
- `python -c "import autospider; import autospider.contexts.planning; import autospider.contexts.collection; import autospider.contexts.experience; import autospider.contexts.chat; import autospider.composition; import autospider.platform"` 无错
- 旧测试文件已经在阶段 2 逐个迁走，这里无遗留

**Commit 消息**：`chore: delete legacy packages (common, crawler, pipeline, graph, field, domain, taskplane*, cli.py)`

### commit[4.2] · 死代码扫除

执行命令并处理输出（都是只读观察，实际修改由本 commit 完成）：

```powershell
ruff check src --select F401,F811,F841,F403,F405,RUF022 --fix
vulture src --min-confidence 70 > refactor/_generated/vulture-report.txt
deptry src > refactor/_generated/deptry-report.txt
python -m pydeps src/autospider --max-bacon 0 --cluster --noshow -o refactor/_generated/deps.svg
```

**本 commit 的动作**：
- 删除 `vulture` 高置信度（≥80）的未用函数/类（保守删）
- 处理 `deptry` 报告中的多余依赖（`pyproject.toml` 调整）
- `pydeps` 产出的依赖图存到 `refactor/_generated/deps.svg` 作为最终架构快照

**Commit 消息**：`chore: dead-code sweep (ruff autofix + vulture + deptry) and dependency graph snapshot`

**打 tag**：`git tag refactor-phase-4`

---

## 阶段 5 · 防腐机制 + 文档

### commit[5.1] · CI / import-linter / pre-commit

**新增**：
- 项目根 `.importlinter`（完整契约，见 `05-guardrails.md §3`）
- `.pre-commit-config.yaml`（见 `05-guardrails.md §4`）
- `pyproject.toml` ruff 配置升级（见 `05-guardrails.md §1`）
- `pyproject.toml` mypy 配置升级（见 `05-guardrails.md §2`）
- `.github/workflows/ci.yml`（或 CI 平台等价，见 `05-guardrails.md §5`；`.github/` 当前在 `.gitignore` 里，本 commit 同时修正 `.gitignore`）

**验证**：
- `lint-imports` 所有契约通过
- `pre-commit run --all-files` 绿
- CI 若可触发则观察跑通

**Commit 消息**：`chore(ci): enforce layered architecture via import-linter + pre-commit + github actions`

### commit[5.2] · 架构文档 + ADR

**新增**：
- `refactor/_generated/architecture.svg`（从 `01-architecture.md` 的 mermaid 导出，可选）
- `refactor/adr/0001-adopt-light-ddd.md`
- `refactor/adr/0002-redis-as-queue-and-store.md`
- `refactor/adr/0003-run-artifact-layout.md`
- `refactor/adr/0004-import-linter-contracts.md`
- 更新 `AGENTS.md`：新目录结构、命令清单（`autospider` CLI 不变）、新测试分类
- 更新 `README.md`：新架构 1 页概览图 + 快速开始
- 标记本重构目录 `refactor/` 为**存档**：在 `refactor/README.md` 顶部加状态 badge "✅ executed at refactor-phase-5"

**Commit 消息**：`docs: architecture, adrs and updated agents/readme after refactor`

**打 tag**：`git tag refactor-phase-5`

---

## 全 commit 清单一览

| # | Commit ID（占位） | 消息摘要 | diff 预估 |
|---|---|---|---|
| 0.1 | — | contracts: cli/redis/output/result snapshots | +400 |
| 0.2 | — | dev: verify script + gitignore fix | +150 |
| 1.1 | — | platform: scaffold + shared kernel | +600 |
| 1.2 | — | platform-obs: logging + contextvars | +350 |
| 1.3 | — | platform-persistence: new db schema + alembic | +500 |
| 1.4 | — | platform-persistence: redis connection + key registry | +350 |
| 1.5 | — | platform-messaging: event/messaging + 2 impls | +700 |
| 2.1.1 | — | chat/domain: migrate models | +250 |
| 2.1.2 | — | chat/application: use cases | +400 |
| 2.1.3 | — | chat/infrastructure: repos + adapters | +350 |
| 2.1.4 | — | chat: wiring + tests | +300 |
| 2.1.5 | — | chat: drop legacy paths | -200 |
| 2.2.1~5 | — | experience context (5 commits) | ±2500 |
| 2.3.1~5 | — | planning context (5 commits) | ±3000 |
| 2.4.1~7 | — | collection context (7 commits) | ±5500 |
| 3.1 | — | composition: wire messaging e2e | +400 |
| 3.2 | — | composition-sagas: collection/recovery/multi-dispatch | +800 |
| 3.3 | — | composition: rewrite langgraph + new cli | +1500 |
| 4.1 | — | chore: delete legacy packages | -15000 |
| 4.2 | — | chore: dead-code sweep | ±500 |
| 5.1 | — | ci: import-linter + pre-commit + github actions | +600 |
| 5.2 | — | docs: architecture + adrs | +800 |

总计约 **25 个 local commit**；执行节奏单人约 **3~5 周**（含测试与调试）。

---

## 回滚矩阵

| 阶段 | 回滚命令 | 影响 |
|---|---|---|
| 任意 commit 出错 | `git reset --hard HEAD~1` | 撤销最近一个 commit |
| 阶段 1 出错 | `git reset --hard refactor-phase-0` | 回到仅含契约快照测试的基线 |
| 阶段 2 某 Context 出错 | `git reset --hard refactor-phase-1` | 回到骨架状态，保留新 DB/Redis 基建 |
| 阶段 3 出错 | `git reset --hard refactor-phase-2` | 回到所有 Context 已迁但无 saga/新 cli |
| 阶段 4 删除失误 | `git reset --hard refactor-phase-3` | 恢复旧包（因为还没物理删） |
| 整体失败 | `git reset --hard <pre-refactor-commit>` | 完全撤销（本地 tag 不会丢，可重开） |

**tag 留存策略**：所有 `refactor-phase-*` tag 长期保留在本地；执行成功后可选择 push 到远端作为历史快照。

---

## 并行化建议（可选）

若团队 >1 人，可在 **阶段 2** 并行：Chat / Experience 两人一组先行，Planning 次之，Collection 必须最后且单人推（依赖最复杂）。仍以 commit 串行合入本地 branch。
