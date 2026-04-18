# 02 · 迁移映射

按模块给出"旧位置 → 新位置"的对照表、10 个巨石文件的详细拆分方案、以及要直接删除的模块清单。执行时按 [`04-execution-plan.md`](./04-execution-plan.md) 的 commit 顺序搬运。

---

## 1. 整体映射（按旧目录一览）

### 1.1 `src/autospider/domain/`（旧）

| 旧文件 | 新位置 | 备注 |
|---|---|---|
| `domain/chat.py` | `contexts/chat/domain/model.py` | `ClarificationResult`、`ClarifiedTask`、`DialogueMessage` |
| `domain/fields.py` | `contexts/collection/domain/field/model.py` | `FieldDefinition` |
| `domain/planning.py` | `contexts/planning/domain/model.py` + `contexts/planning/domain/services.py` | `TaskPlan`、`SubTask`、`SubTaskStatus` 拆到 model；编排逻辑到 services |
| `domain/runtime.py` | `platform/shared_kernel/runtime.py` 或 `contexts/collection/domain/model.py` | `SubTaskRuntimeState`、`SubTaskRuntimeSummary`；若仅 Collection 用则归入 Collection |

### 1.2 `src/autospider/common/`（旧，整体拆散）

| 旧子目录/文件 | 新位置 |
|---|---|
| `common/config.py` | `platform/config/settings.py`（重写为 pydantic-settings） |
| `common/logger.py` | `platform/observability/logging.py` |
| `common/exceptions.py` | 业务异常 → 各 Context `domain/errors.py`；基础设施异常 → `platform/shared_kernel/errors.py` |
| `common/constants.py` | 按领域拆：浏览器相关 → `platform/browser/constants.py`；其余 → `platform/shared_kernel/constants.py` |
| `common/types.py` | 领域类型 → 对应 Context `domain/model.py`；通用 → `platform/shared_kernel/` |
| `common/protocol.py` (600L) | 拆分：LLM 协议 → `platform/llm/protocol.py`；域协议 → 对应 Context `domain/ports.py` |
| `common/llm_contracts.py` | 同 `protocol.py`，拆到 `platform/llm/` 与 Context `domain/` |
| `common/validators.py` | 领域规则 → 各 Context `domain/services.py`；通用验证 → `platform/shared_kernel/validators.py` |
| `common/decision_context_format.py` | `composition/graph/decision_context.py` |
| `common/grouping_semantics.py` | `contexts/collection/domain/services.py`（属于采集语义） |
| `common/accessibility.py` | `platform/browser/accessibility.py` |
| `common/browser/` | `platform/browser/` |
| `common/som/` | `platform/browser/som/` |
| `common/llm/` | `platform/llm/` |
| `common/channel/` | `platform/messaging/`（见 §1.5） |
| `common/db/` | `platform/persistence/sql/` |
| `common/storage/redis_manager.py`、`redis_pool.py` | `platform/persistence/redis/` + `platform/messaging/redis_streams.py`（队列部分） |
| `common/storage/collection_persistence.py` | `contexts/collection/infrastructure/repositories/run_repository.py` |
| `common/storage/field_xpath_*.py` | `contexts/collection/infrastructure/repositories/field_xpath_repository.py` |
| `common/storage/pipeline_runtime_store.py` | `composition/graph/state_store.py`（LangGraph 编排态） |
| `common/storage/task_run_query_service.py` | `contexts/collection/application/use_cases/query_runs.py`（查询用例） |
| `common/storage/idempotent_io.py` | `platform/persistence/files/idempotent_io.py` |
| `common/experience/skill_runtime.py` | `contexts/experience/application/use_cases/`（拆为多个用例文件） |
| `common/experience/skill_sedimenter.py` (1050L) | 见 §2 巨石拆分 |
| `common/experience/skill_store.py` (1014L) | 见 §2 巨石拆分 |
| `common/utils/delay.py` | `platform/shared_kernel/time.py` |
| `common/utils/paths.py` | `platform/shared_kernel/paths.py` |
| `common/utils/string_maps.py` | `platform/shared_kernel/string_maps.py` |
| `common/utils/file_utils.py` | `platform/persistence/files/file_utils.py` |
| `common/utils/prompt_template.py` | `platform/llm/prompts_loader.py` |
| `common/utils/fuzzy_search.py` (841L) | `contexts/collection/domain/field/fuzzy_search.py`（作为字段匹配规则，领域纯函数） |

### 1.3 `src/autospider/crawler/`（旧）

| 旧子目录/文件 | 新位置 |
|---|---|
| `crawler/planner/task_planner.py` (973L) | 见 §2 巨石拆分 |
| `crawler/planner/planner_state.py` | 合并进 `contexts/planning/domain/model.py` |
| `crawler/planner/planner_analysis_postprocess.py` | `contexts/planning/application/use_cases/analyze_plan_result.py` |
| `crawler/planner/planner_artifacts.py` | `contexts/planning/infrastructure/repositories/artifact_store.py` |
| `crawler/planner/planner_category_semantics.py` | `contexts/planning/domain/services.py`（语义分类规则） |
| `crawler/planner/planner_subtask_builder.py` | `contexts/planning/domain/services.py`（`PlanDecomposer`） |
| `crawler/planner/planner_variant_resolver.py` | `contexts/collection/domain/policies.py`（`VariantResolver` 实际归采集决策） |
| `crawler/planner/runtime.py` | `contexts/planning/application/handlers.py`（运行时事件处理） |
| `crawler/base/base_collector.py` (685L) | 抽象部分 → `contexts/collection/domain/services.py`；实现 → `contexts/collection/application/use_cases/run_subtask.py` |
| `crawler/base/progress_store.py` | `contexts/collection/infrastructure/repositories/progress_repository.py` |
| `crawler/base/url_publish_service.py` | `contexts/collection/application/use_cases/publish_urls.py` |
| `crawler/batch/batch_collector.py` | 合并到 `run_subtask.py`（批量只是策略差异） |
| `crawler/explore/url_collector.py` | `contexts/collection/application/use_cases/collect_urls.py` |
| `crawler/explore/shared_workflow.py` | `contexts/collection/application/use_cases/explore_site.py` |
| `crawler/explore/config_generator.py` | `contexts/planning/application/use_cases/generate_crawler_config.py` |
| `crawler/collector/llm_decision.py` | `contexts/collection/infrastructure/adapters/llm_navigator.py` |
| `crawler/collector/models.py` | 合并进 `contexts/collection/domain/model.py` |
| `crawler/collector/navigation_handler.py` (613L) | `contexts/collection/application/use_cases/navigate.py` + `domain/services.py`（NavigationPlanner） |
| `crawler/collector/pagination_handler.py` (631L) | `contexts/collection/application/use_cases/paginate.py` + `domain/services.py`（PaginationStrategy） |
| `crawler/collector/page_utils.py` | `platform/browser/page_utils.py` |
| `crawler/collector/url_extractor.py` | `contexts/collection/application/use_cases/extract_urls.py` |
| `crawler/collector/xpath_extractor.py` | `contexts/collection/domain/field/xpath/extractor.py`（纯算法部分） |
| `crawler/checkpoint/*` | `composition/graph/checkpoint.py` |
| `crawler/output/script_generator.py` (563L) | `contexts/collection/application/use_cases/generate_script.py` + `contexts/collection/infrastructure/adapters/scrapy_generator.py` |

### 1.4 `src/autospider/field/`（旧）

| 旧文件 | 新位置 |
|---|---|
| `field/__init__.py` | 删除（不再作为独立顶级模块） |
| `field/field_config.py` | `contexts/collection/domain/field/config.py` |
| `field/field_decider.py` (654L) | `contexts/collection/application/use_cases/decide_fields.py` + `infrastructure/adapters/llm_field_decider.py` |
| `field/field_extractor.py` (1150L) | 见 §2 巨石拆分 |
| `field/batch_field_extractor.py` | `contexts/collection/application/use_cases/extract_fields_batch.py` |
| `field/batch_xpath_extractor.py` | `contexts/collection/application/use_cases/extract_xpaths_batch.py` |
| `field/detail_page_worker.py` | `contexts/collection/application/use_cases/process_detail_page.py` |
| `field/models.py` | `contexts/collection/domain/field/model.py` |
| `field/runner.py` | 合并到 `contexts/collection/application/use_cases/run_subtask.py` |
| `field/skill_context.py` | `contexts/collection/application/handlers.py`（订阅 Experience 事件） |
| `field/value_helpers.py` | `contexts/collection/domain/field/value_helpers.py` |
| `field/xpath_helpers.py` | `contexts/collection/domain/field/xpath/helpers.py` |
| `field/xpath_pattern.py` (1292L) | 见 §2 巨石拆分 |

### 1.5 `src/autospider/pipeline/`、`graph/`、`taskplane*/`（旧）

| 旧文件 | 新位置 |
|---|---|
| `pipeline/runner.py` (825L) | 见 §2 巨石拆分 |
| `pipeline/orchestration.py` | `composition/sagas/collection_saga.py` |
| `pipeline/worker.py` | `contexts/collection/application/use_cases/run_subtask.py`（work loop） |
| `pipeline/subtask_runtime.py` | `contexts/collection/domain/model.py`（运行时聚合） |
| `pipeline/aggregator.py` | `contexts/collection/application/use_cases/finalize_run.py`（聚合部分） |
| `pipeline/finalization.py` (798L) | 见 §2 巨石拆分 |
| `pipeline/helpers.py` | 根据内容拆到 `contexts/collection/application/` 或删除 |
| `pipeline/progress_tracker.py` | `contexts/collection/application/handlers.py` |
| `pipeline/run_store.py` + `run_store_async.py` | `platform/persistence/redis/run_store.py`（统一） |
| `pipeline/runtime_controls.py` | `composition/graph/controls.py`（中断/恢复控制） |
| `pipeline/types.py` (大型 DTO) | 拆分：领域 DTO → 对应 Context；编排 DTO → `composition/graph/state.py` |
| `graph/main_graph.py` | `composition/graph/main_graph.py` |
| `graph/runner.py` | 合并进 `composition/use_cases/run_chat_pipeline.py` |
| `graph/state.py`、`state_access.py`、`workflow_access.py`、`workflow_state.py` | `composition/graph/state.py`（单一事实源） |
| `graph/decision_context.py` | `composition/graph/decision_context.py` |
| `graph/execution_handoff.py` | `composition/graph/handoff.py` |
| `graph/failures.py` | `contexts/planning/domain/policies.py`（`FailureClassifier`） |
| `graph/recovery.py` | `composition/sagas/recovery_saga.py` |
| `graph/world_model.py` | `contexts/collection/domain/services.py`（世界模型属于采集领域） |
| `graph/control_types.py` | `composition/graph/controls.py` |
| `graph/types.py` | 拆分到对应领域 |
| `graph/checkpoint.py` | `composition/graph/checkpoint.py` |
| `graph/nodes/*` (5 文件 × 合计 ~72k bytes) | `composition/graph/nodes/` 按职责重组：`plan_nodes.py`、`collect_nodes.py`、`finalize_nodes.py`、`recovery_nodes.py`（每个节点仅调用 Application Service） |
| `graph/subgraphs/multi_dispatch.py` | `composition/sagas/multi_dispatch_saga.py` |
| `taskplane/` 整个 | 合并进 `contexts/planning/application/` + `composition/`，不再独立 |
| `taskplane_adapter/` 整个 | **删除**，能力迁入 `composition/sagas/` |
| `cli.py` (1014L) | 见 §2 巨石拆分 |
| `cli_runtime.py` | 合并进 `composition/container.py` + 各 `interface/cli/*.py` |

---

## 2. 巨石文件拆分详细清单

### 2.1 `field/xpath_pattern.py`（1292 行）

**现状**：XPath 模式识别、相似度计算、规则应用混在一起。

**新位置**：`contexts/collection/domain/field/xpath/`

| 新文件 | 职责 | 预估行数 |
|---|---|---|
| `patterns.py` | XPath 模式的数据类型与枚举（纯类型） | ~200 |
| `normalizer.py` | XPath 规范化/简化规则 | ~200 |
| `matcher.py` | 两条 XPath 的匹配度计算 | ~250 |
| `scorer.py` | 稳定性/泛化度打分 | ~200 |
| `generator.py` | 从 DOM 节点生成候选 XPath | ~250 |
| `__init__.py` | 公开 API re-export | ~30 |

**拆分顺序**：先抽出 `patterns.py`（纯类型）→ 再抽 `normalizer.py`（无依赖）→ 再抽 `matcher.py`（依赖前两者）→ 最后 `scorer.py` 与 `generator.py`。每一步独立 commit + 测试绿。

### 2.2 `field/field_extractor.py`（1150 行）

**新位置**：
- `contexts/collection/application/field_extraction/`（用例）
- `contexts/collection/domain/field/rules.py`（规则）

| 新文件 | 职责 | 预估行数 |
|---|---|---|
| `application/field_extraction/page_extractor.py` | 单页字段提取用例（visible 版） | ~350 |
| `application/field_extraction/batch_extractor.py` | 批量字段提取用例（XPath 复用版） | ~350 |
| `application/field_extraction/pipeline.py` | 提取 pipeline 编排（LLM 决策 → XPath 验证 → 值归一） | ~250 |
| `domain/field/rules.py` | 字段值验证/归一规则（纯函数） | ~200 |

### 2.3 `common/experience/skill_sedimenter.py`（1050 行）

**新位置**：`contexts/experience/`

| 新文件 | 职责 | 预估行数 |
|---|---|---|
| `domain/services.py` | `SkillSedimenter`（算法纯函数） | ~400 |
| `domain/policies.py` | 沉淀策略（何时沉淀、如何合并） | ~200 |
| `application/use_cases/sediment_skill.py` | 沉淀用例（读取 run → 调 domain → 存储） | ~250 |
| `application/use_cases/merge_skills.py` | 技能合并用例 | ~200 |

### 2.4 `common/experience/skill_store.py`（1014 行）

**新位置**：`contexts/experience/infrastructure/repositories/`

| 新文件 | 职责 | 预估行数 |
|---|---|---|
| `skill_repository.py` | Skill 聚合的 CRUD | ~350 |
| `skill_index_repository.py` | 按 site/field 索引查询 | ~250 |
| `skill_serializer.py` | Skill 与 Redis Hash 的序列化 | ~200 |
| `skill_query_service.py` | 复杂查询（按相似度、按命中率） | ~250 |

### 2.5 `cli.py`（1014 行）

**新位置**：`interface/cli/`

| 新文件 | 职责 | 预估行数 |
|---|---|---|
| `__init__.py` | Typer `app` 组装与注册所有子命令 | ~80 |
| `chat_pipeline.py` | `autospider chat-pipeline` 子命令 | ~200 |
| `resume.py` | `autospider resume` 子命令 | ~150 |
| `doctor.py` | `autospider doctor` 子命令 | ~150 |
| `benchmark.py` | benchmark 相关子命令 | ~250 |
| `redis_ops.py` | redis 运维子命令 | ~150 |
| `_rendering.py` | Rich 渲染工具（表格/面板） | ~100 |

**不再保留** `_CliRuntimeProxy` 惰性代理——通过 `composition/container.py` 显式组装依赖，import cycle 通过分层本身消除。

### 2.6 `crawler/planner/task_planner.py`（973 行）

**新位置**：`contexts/planning/`

| 新文件 | 职责 | 预估行数 |
|---|---|---|
| `domain/services.py` | `PlanDecomposer`（纯算法部分） | ~250 |
| `domain/policies.py` | `FailureClassifier`、`ReplanStrategy` | ~200 |
| `application/use_cases/create_plan.py` | 首次规划用例 | ~150 |
| `application/use_cases/replan.py` | 重新规划用例 | ~150 |
| `application/use_cases/classify_runtime_exception.py` | 运行时异常分类 | ~120 |
| `application/handlers.py` | 订阅 `collection.SubTaskFailed` → 触发 replan | ~100 |

### 2.7 `pipeline/runner.py`（825 行）

**新位置**：拆分到 `composition/` 与 `contexts/collection/`

| 新文件 | 职责 | 预估行数 |
|---|---|---|
| `composition/use_cases/run_chat_pipeline.py` | CLI 入口用例：组装 → 启动 Graph → 渲染结果 | ~250 |
| `composition/sagas/collection_saga.py` | 采集 saga（替代 `pipeline/orchestration.py`） | ~300 |
| `contexts/collection/application/use_cases/run_subtask.py` | 单个 SubTask 执行 | ~250 |

### 2.8 `common/storage/redis_manager.py`（806 行）

**新位置**：`platform/`

| 新文件 | 职责 | 预估行数 |
|---|---|---|
| `platform/persistence/redis/connection.py` | 连接池、健康检查 | ~150 |
| `platform/persistence/redis/keys.py` | 集中 key registry（见 `03-contracts.md §2`） | ~200 |
| `platform/persistence/redis/base_repository.py` | 通用 Hash/Set/ZSet 操作封装 | ~200 |
| `platform/messaging/redis_streams.py` | Streams 实现（Lua 脚本：push/fetch/fail） | ~300 |

### 2.9 `pipeline/finalization.py`（798 行）

**新位置**：拆到两处

| 新文件 | 职责 | 预估行数 |
|---|---|---|
| `composition/sagas/collection_saga.py` | 跨 Context 编排（接收 Collection 结束 → 触发 Experience 沉淀） | （与 2.7 合并） |
| `contexts/collection/application/use_cases/finalize_run.py` | Collection 内部的聚合与落盘 | ~400 |
| `platform/persistence/files/artifact_writer.py` | 产物目录写入（见 `03-contracts.md §6`） | ~200 |

### 2.10 `graph/nodes/capability_nodes.py`（789 行）+ `entry_nodes.py`（772 行）

**新位置**：`composition/graph/nodes/`

| 新文件 | 职责 | 预估行数 |
|---|---|---|
| `plan_nodes.py` | 规划节点（调 Planning use case） | ~200 |
| `collect_nodes.py` | 采集节点 | ~250 |
| `finalize_nodes.py` | 结束节点 | ~200 |
| `recovery_nodes.py` | 恢复/失败处理节点 | ~200 |
| `entry_nodes.py` | 图入口（澄清 → 规划） | ~200 |

所有节点严格遵循"薄包装"：`def node(state): result = use_case.run(...); return update_state(state, result)`。

---

## 3. 直接删除清单（无替代）

以下模块在新架构中没有对应位置，阶段 4 `commit[4.1]` 统一删除：

- `src/autospider/taskplane_adapter/`（整包）：旧的图集成桥，职责被 `composition/` 吸收
- `src/autospider/artifacts/`（空目录）
- `src/autospider/output/`（空目录，实际产物位于仓库根 `output/`）
- `src/autospider/field/`（顶级包，拆散到 `contexts/collection/` 后删除）
- `src/autospider/domain/`（旧 domain，迁移到 `contexts/*/domain/` 后删除）
- `src/autospider/common/`（迁移完毕后整体删除）
- `src/autospider/crawler/`（迁移完毕后整体删除）
- `src/autospider/pipeline/`（迁移完毕后整体删除）
- `src/autospider/graph/`（迁移完毕后整体删除）
- `src/autospider/taskplane/`（迁移到 `contexts/planning/` + `composition/` 后删除）
- `src/autospider/cli.py`、`src/autospider/cli_runtime.py`（迁到 `interface/cli/` 后删除）
- 项目根 `check_elements.py`（临时调试脚本，删除）

---

## 4. 测试迁移

当前 `tests/` 40+ 扁平测试按 Context / 层级重组：

```text
tests/
├── contracts/                 # 阶段 0 新增，端到端契约快照
│   ├── test_cli_surface.py
│   ├── test_redis_keys_surface.py
│   ├── test_output_layout.py
│   └── test_result_envelope.py
├── contexts/
│   ├── planning/
│   │   ├── domain/            # 纯领域测试（无 mock，无 I/O）
│   │   └── application/       # 用 fake repository + fake messaging
│   ├── collection/
│   ├── experience/
│   └── chat/
├── composition/
│   ├── graph/                 # LangGraph 节点单测
│   └── sagas/                 # Saga 状态流转测试
├── platform/
│   ├── messaging/
│   ├── persistence/
│   └── browser/
├── interface/
│   └── cli/                   # Typer CliRunner
├── e2e/                       # 现有 e2e 移入（已有目录标记）
└── benchmark/                 # 保持现状
```

旧 `tests/test_*.py` 文件的迁移映射（示例，完整列表在 commit[2.x.5] 中逐个迁）：

| 旧 | 新 |
|---|---|
| `tests/test_pipeline_finalization.py` | `tests/contexts/collection/application/test_finalize_run.py` |
| `tests/test_failure_classifier.py` | `tests/contexts/planning/domain/test_failure_classifier.py` |
| `tests/test_redis_channel_behavior.py` | `tests/platform/messaging/test_redis_streams.py` |
| `tests/test_graph_runner.py` | `tests/composition/use_cases/test_run_chat_pipeline.py` |
| `tests/test_task_planner_prior_failures.py` | `tests/contexts/planning/application/test_replan.py` |
| `tests/test_decision_context*.py` | `tests/composition/graph/test_decision_context.py` |
| `tests/test_entry_nodes_runtime_handoff.py` | `tests/composition/graph/test_entry_nodes.py` |
| ... | ... |

`tests/autospider_next/` 与 `tests/unit/`（空壳）在 `commit[4.1]` 一并删除。

---

## 5. 迁移顺序总结（按依赖拓扑）

从叶子 Context 到根 Context、从 Platform 到 Composition：

1. 先搭 `platform/shared_kernel`（无依赖）
2. 搭 `platform/observability` / `platform/config`
3. 搭 `platform/persistence`（Redis connection + keys + SQL engine + Alembic）
4. 搭 `platform/messaging`
5. 搭 `platform/browser` / `platform/llm`
6. 迁 Context：`chat` → `experience` → `planning` → `collection`（依赖从少到多）
7. 迁 `composition/`（依赖所有 Context）
8. 迁 `interface/cli/`
9. 删旧包

具体 commit 划分见 [`04-execution-plan.md`](./04-execution-plan.md)。
