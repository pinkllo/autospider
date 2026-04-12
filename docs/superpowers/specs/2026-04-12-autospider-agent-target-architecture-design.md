# AutoSpider 智能体目标架构设计

**日期：** 2026-04-12

## 目标

为 AutoSpider 定义一套完整的目标架构，使系统从“多个能力节点串联的采集流程”演进为“具备认知连续体、分层控制、显式反馈闭环的采集智能体系统”。

本设计不推翻现有 `LangGraph + pipeline + worker` 基座，而是在保留主执行路径的前提下，重构状态模型、认知传递、控制策略和失败反馈机制。

## 设计原则

### 单一事实源

- 每类核心数据只能有一个权威位置。
- 不允许通过“顶层字段 + 子状态字段 + 回退优先级”共同表达同一事实。
- Selector 只做类型安全访问，不做语义 merge。

### 认知连续体

- 用户意图、页面结构、导航经验、失败证据必须进入统一世界模型。
- 任意阶段产生的高价值知识，都必须能被后续阶段直接消费。
- 系统不得让 planner、collector、extractor 在同一问题上重复从零理解。

### 分层控制

- 规划、调度、执行、反馈必须分层。
- 上层决定目标与策略，下层负责执行与观测。
- 执行层不得隐式重写战略目标，控制层不得直接承担页面交互细节。

### 显式失败

- 失败是系统的一等公民，不是日志副产物。
- 所有失败必须结构化记录：失败类型、上下文、证据、已尝试恢复动作、最终处置。
- 不允许通过静默 fallback 掩盖状态错配、契约违背或认知失真。

### 可验证演进

- 目标架构必须支持分阶段落地。
- 每一阶段都要保留系统可运行、可测试、可回滚的状态。

## 现状问题归纳

### 状态层问题

- `GraphState` 同时承载元数据、阶段结果、临时节点输出、错误、汇总和兼容字段。
- `task_plan`、`plan_knowledge`、`subtask_results`、`error` 等信息被多处重复表达。
- `state_access.py` 通过回退与 merge 拼装业务语义，导致调试路径不透明。

### 认知层问题

- `TaskClarifier`、历史任务匹配、`TaskPlanner`、导航决策器各自单独推理。
- planner 产出的知识虽然能被持久化，但执行期决策基本不直接消费。
- 失败信息大多停留在 trace、summary 和日志中，难以形成可复用经验。

### 控制层问题

- 规划与执行有分离，但缺少稳定的战术层和反馈控制层。
- 当前主要依靠一次性 plan 和局部重试，缺少“执行中修正策略”的位置。
- `_run_with_retry()` 把不同错误都当作同一类问题处理。

### 契约层问题

- LLM 输出已经具备基础校验层，但业务节点仍大量依赖推断修复。
- 协议失败后没有统一的修复器与升级路径，而是散落在各节点内部。

## 目标系统形态

目标系统由五层组成：

1. 意图层 `Intent Layer`
2. 世界模型层 `World Model Layer`
3. 控制层 `Control Layer`
4. 执行层 `Execution Layer`
5. 反馈层 `Feedback Layer`

总体数据流：

```text
User Request
-> Intent Layer
-> World Model Initialization
-> Strategic Planning
-> Tactical Dispatch
-> Execution
-> Feedback Classification
-> World Model Update
-> Replan / Continue / Escalate
-> Result Aggregation
```

## 核心状态模型

目标状态不再使用“大顶层状态 + 若干兼容字段”的方式，而是定义清晰的域状态。

```python
class WorkflowState(TypedDict):
    meta: MetaState
    intent: IntentState
    world: WorldModelState
    control: ControlState
    execution: ExecutionState
    result: ResultState
```

### MetaState

```python
class MetaState(TypedDict):
    thread_id: str
    request_id: str
    entry_mode: str
    lifecycle_status: str
```

职责：

- 承载线程、请求、入口模式、全局生命周期状态。
- 不承载业务语义。

### IntentState

```python
class IntentState(TypedDict):
    status: str
    request_text: str
    clarified_task: dict[str, Any] | None
    fields: list[dict[str, Any]]
    constraints: dict[str, Any]
    chat_history: list[dict[str, str]]
    selected_skills: list[dict[str, str]]
    clarification_trace: list[dict[str, Any]]
```

职责：

- 承载用户需求的权威表达。
- `fields`、`constraints`、`selected_skills` 只存在于这里。
- 所有后续节点只能从这里读取任务语义。

### WorldModelState

```python
class WorldModelState(TypedDict):
    site_profile: dict[str, Any]
    page_models: dict[str, dict[str, Any]]
    navigation_memory: dict[str, Any]
    extraction_memory: dict[str, Any]
    active_hypotheses: list[dict[str, Any]]
    invalidated_hypotheses: list[dict[str, Any]]
    evidence_log: list[dict[str, Any]]
```

职责：

- 承载跨节点共享认知。
- 统一记录“系统当前认为这个站点和这个页面是什么”。
- 任何认知修正都写回这里，而不是只写日志。

### ControlState

```python
class ControlState(TypedDict):
    current_plan: dict[str, Any] | None
    dispatch_policy: dict[str, Any]
    active_strategy: dict[str, Any]
    recovery_policy: dict[str, Any]
    decision_context: dict[str, Any]
    checkpoints: list[dict[str, Any]]
```

职责：

- 承载当前计划、调度策略、恢复策略和执行检查点。
- `task_plan` 只存在于 `current_plan`。

### ExecutionState

```python
class ExecutionState(TypedDict):
    stage: str
    current_subtask: dict[str, Any] | None
    runtime_context: dict[str, Any]
    collected_urls: list[str]
    collection_config: dict[str, Any] | None
    extraction_config: dict[str, Any] | None
    action_trace: list[dict[str, Any]]
    failures: list[dict[str, Any]]
```

职责：

- 承载真实运行过程。
- 节点的临时输出都应收口到这里，不允许继续写 `node_payload`/`node_error` 一类兼容结构。

### ResultState

```python
class ResultState(TypedDict):
    summary: dict[str, Any]
    artifacts: list[dict[str, str]]
    final_error: dict[str, str] | None
```

职责：

- 只承载最终产物和最终结论。
- 不再兼容阶段中间态。

## 世界模型设计

世界模型是整套目标架构的核心，用于解决当前“知识可传输但难消费”的问题。

### PageModel

```python
class PageModel(TypedDict):
    page_id: str
    url_pattern: str
    page_type: str
    structural_features: dict[str, Any]
    likely_actions: list[str]
    extraction_hints: dict[str, Any]
    confidence: float
    source: str
```

用途：

- planner 首次分析页面后，写入 `page_models`。
- collector、decider、field extractor 读取 `page_type`、`structural_features`、`extraction_hints`。
- 当执行期发现页面不符合预期时，触发模型修正，而不是继续盲走。

### Hypothesis

```python
class Hypothesis(TypedDict):
    hypothesis_id: str
    kind: str
    statement: str
    supporting_evidence: list[str]
    confidence: float
    status: str
```

状态值：

- `active`
- `confirmed`
- `invalidated`

用途：

- 表达“当前系统为什么相信这是一张列表页”“为什么相信该入口能通往详情页”等认知。
- 执行失败时不直接丢弃认知，而是将假设标记为 `invalidated` 并触发重规划。

### EvidenceLog

统一记录以下事实：

- planner 观察到的页面结构证据
- collector 的点击与验证结果
- extractor 的字段验证证据
- monitor 的失败分类结果

记录格式：

```python
class EvidenceRecord(TypedDict):
    record_id: str
    stage: str
    subject: str
    observation: str
    payload: dict[str, Any]
    created_at: str
```

要求：

- 所有高价值判断都必须有证据来源。
- 证据写入世界模型后，后续节点可消费，不再依赖散落日志。

## 分层控制设计

### Strategic Planner

职责：

- 基于 `IntentState + WorldModelState` 生成初始任务计划。
- 明确目标、约束、成功标准、关键假设和风险点。

输出：

```python
class PlanSpec(TypedDict):
    plan_id: str
    objective: str
    subtasks: list[dict[str, Any]]
    success_criteria: dict[str, Any]
    assumptions: list[str]
    risk_points: list[str]
```

要求：

- plan 不再是纯子任务列表，而是包含成功标准和假设。
- `success_criteria` 必须进入执行期上下文。

### Tactical Dispatcher

职责：

- 根据世界模型和实时反馈选择当前应该执行的子任务。
- 根据失败模式切换策略，而不是只顺序消费计划。

输出：

```python
class DispatchDecision(TypedDict):
    subtask_id: str
    strategy: str
    priority: int
    recovery_mode: str
    hints: dict[str, Any]
```

典型策略：

- 正常收集
- 保守导航
- 重新分析页面
- 人工接管等待
- 跳过并继续其它子任务

### Execution Supervisor

职责：

- 承接 `DispatchDecision` 执行单个 subtask。
- 收集 action trace、局部失败、验证结果。
- 不负责决定全局重排和终局策略。

### Monitor / Feedback Controller

职责：

- 观察执行结果，分类失败，产出恢复指令。
- 更新假设状态，必要时触发 replan。

输出：

```python
class RecoveryDirective(TypedDict):
    action: str
    reason: str
    updates_world_model: bool
    replan_required: bool
    requires_human: bool
```

## 决策上下文设计

所有执行期 LLM 必须消费统一的 `DecisionContext`，不再各自从状态中拼接输入。

```python
class DecisionContext(TypedDict):
    intent: dict[str, Any]
    page_model: dict[str, Any] | None
    active_hypotheses: list[dict[str, Any]]
    selected_skills_context: str
    recent_failures: list[dict[str, Any]]
    recent_actions: list[dict[str, Any]]
    success_criteria: dict[str, Any]
```

约束：

- planner 分析出的 `page_type` 必须能进入 collector/decider。
- extractor 必须能读取相关页面的结构模型与字段提取提示。
- 失败反馈必须进入 `recent_failures`，而不是只在日志可见。

## 错误恢复架构

目标架构中，错误必须先分类，再恢复。

### FailureRecord

```python
class FailureRecord(TypedDict):
    code: str
    category: str
    stage: str
    message: str
    cause: str
    retryable: bool
    requires_strategy_switch: bool
    requires_human: bool
    context: dict[str, Any]
    attempted_recoveries: list[dict[str, Any]]
```

### 错误分类

- `TRANSIENT`
- `CONTRACT_VIOLATION`
- `STATE_MISMATCH`
- `SITE_DEFENSE`
- `RULE_STALE`
- `FATAL`

### 恢复动作

`TRANSIENT`

- 指数退避重试。
- 保留最大次数，但次数由策略配置决定，而不是写死在节点内部。

`CONTRACT_VIOLATION`

- 记录协议失败上下文。
- 进入显式 repair 流程或重问 LLM。
- 禁止静默猜测最终业务动作。

`STATE_MISMATCH`

- 重新扫描页面。
- 刷新 `PageModel` 和相关假设。
- 如仍不一致，触发重新规划。

`SITE_DEFENSE`

- 标记人工接管必需。
- 进入 browser intervention。

`RULE_STALE`

- 标记规则失效。
- 重新归纳导航或字段规则。

`FATAL`

- 立即终止。
- 暴露错误并进入最终结果。

## LLM 契约设计

系统继续使用结构化输出，但从“校验 + 节点内推断修复”升级为“强契约 + 显式修复器”。

### 协议对象

- `ClarificationDecision`
- `PlanningDecision`
- `ActionDecision`
- `RepairDecision`

### ActionDecision

```python
class ActionDecision(BaseModel):
    action: Literal[
        "click", "type", "scroll", "navigate", "wait",
        "extract", "go_back", "go_back_tab", "done"
    ]
    target: dict[str, Any] | None = None
    rationale: str
    expected_observation: str
    confidence: float
```

约束：

- 协议解析失败时，进入 `RepairDecision`，而不是直接根据 `args` 猜动作。
- repair 行为必须写入 evidence 与 failure records。

### RepairDecision

```python
class RepairDecision(BaseModel):
    repair_type: Literal["reask", "downgrade_context", "terminate"]
    reason: str
```

目的：

- 将当前零散的 `_normalize_result()`、动作自动推断、隐式 retry 统一收口。

## 节点职责重构

目标图流如下：

```text
Entry
-> ClarifyIntent
-> InitializeWorldModel
-> PlanStrategy
-> DispatchSubtask
-> ExecuteSubtask
-> MonitorOutcome
-> UpdateWorldModel
-> ReplanOrContinue
-> AggregateResult
-> FinalizeRun
```

### ClarifyIntent

- 只负责产出 `IntentState`
- 写入字段、约束、澄清轨迹

### InitializeWorldModel

- 加载站点历史经验
- 结合意图生成初始世界模型

### PlanStrategy

- 生成 `PlanSpec`
- 产出初始 `page_models`、`hypotheses`、`success_criteria`

### DispatchSubtask

- 选择当前要执行的子任务
- 绑定执行策略和恢复策略

### ExecuteSubtask

- 运行 worker / pipeline
- 产出 action trace、局部结果、局部失败

### MonitorOutcome

- 分类执行结果
- 生成 `RecoveryDirective`

### UpdateWorldModel

- 更新 `page_models`
- 确认或作废假设
- 写入 evidence

### ReplanOrContinue

- 决定继续、重排、升级人工接管或终止

### AggregateResult

- 聚合跨子任务结果
- 只处理结果，不再负责补齐中间状态

### FinalizeRun

- 写最终 summary
- 写 artifacts
- 晋升已验证 skill
- 沉淀失败模式

## 学习与沉淀机制

目标系统要区分三类沉淀：

### 成功规则沉淀

- 仅对稳定成功、验证通过的规则生成正式 skill / xpath 规则。
- 保留现有严格门槛。

### 失败模式沉淀

- 失败不晋升为正式 skill。
- 但必须沉淀为 `FailurePattern`，供后续控制层使用。

```python
class FailurePattern(TypedDict):
    pattern_id: str
    trigger: str
    affected_stage: str
    recommended_recovery: str
    confidence: float
```

### 站点画像沉淀

- 形成 `SiteProfile`，记录站点的稳定结构、反爬信号、导航规律和常见失败模式。

```python
class SiteProfile(TypedDict):
    host: str
    common_page_patterns: list[dict[str, Any]]
    anti_bot_signals: list[str]
    stable_navigation_rules: list[dict[str, Any]]
    known_failure_modes: list[dict[str, Any]]
```

## 与现有代码的映射关系

### `graph/state.py`

- 将被新的域状态定义替代。
- 顶层兼容字段逐步删除，不再继续增加。

### `graph/state_access.py`

- 从“回退拼装器”重构为“单一事实源 accessor”。
- 不再 merge 业务语义。

### `graph/nodes/entry_nodes.py`

- 收敛为意图层入口节点。
- 只负责澄清、历史上下文引导和进入 `IntentState`。

### `graph/nodes/capability_nodes.py`

- 拆分为 planning、execution、feedback 三类节点文件。
- 删除统一 `_run_with_retry()` 的全局耦合地位。

### `crawler/planner/task_planner.py`

- 升级为“初始世界模型构建器 + 初始计划生成器”。
- 不再只返回 subtasks。

### `pipeline/runner.py`

- 输入变成 `DispatchDecision + DecisionContext`。
- 运行期反馈返回结构化执行报告。

### `pipeline/finalization.py`

- 保留 summary / artifact 汇总。
- 新增失败模式沉淀。

## 迁移策略

目标架构按四阶段迁移：

### 阶段 1：状态收口

- 建立新 `WorkflowState`
- 保留旧字段只做兼容映射
- 新节点只写新状态，不写顶层冗余字段

验收标准：

- 新增 accessor 全部基于单一事实源。
- `task_plan`、`subtask_results`、`error` 不再出现多位置写入。

### 阶段 2：世界模型落地

- 引入 `WorldModelState`
- planner 写入 `page_models`、`hypotheses`、`evidence_log`
- collector / extractor 读取 `DecisionContext`

验收标准：

- planner 的页面分类结果进入执行期 prompt。
- 执行失败能反向更新页面模型。

### 阶段 3：控制与恢复分层

- 引入 `DispatchDecision`、`RecoveryDirective`
- 错误统一分类
- 将 `_run_with_retry()` 替换为策略驱动恢复

验收标准：

- 不同错误类别走不同恢复动作。
- browser intervention、state mismatch、contract violation 不再共用同一重试逻辑。

### 阶段 4：学习闭环

- 引入 `FailurePattern`、`SiteProfile`
- 失败知识写回世界模型和站点画像
- 正式 skill 晋升与失败诊断沉淀分离

验收标准：

- 失败后可追溯“系统学到了什么”。
- 下一轮执行可消费已沉淀的失败模式。

## 风险与边界

### 复杂度风险

- 新增世界模型和控制层会提高抽象层级。
- 必须控制每个模块的职责，避免再造一个更大的 God object。

### 兼容期风险

- 新旧状态并存的过渡期最容易出现读写分叉。
- 必须尽快完成“新写旧读”到“新写新读”的切换。

### 性能风险

- `evidence_log` 与世界模型快照可能增大状态体积。
- 需要定义裁剪策略，只保留近期执行上下文和高价值证据摘要。

### 边界约束

- 不引入静默 fallback。
- 不因为目标架构复杂就临时增加“最大轮数保护”之类的隐式边界规则。
- 人工接管仍保留为显式状态，而非失败分支伪装。

## 验证策略

### 单元测试

- 状态 accessor 只能读取单一事实源
- 错误分类器的类别判断
- 世界模型更新逻辑
- 假设确认与作废逻辑
- 决策上下文构建逻辑

### 集成测试

- planner -> world model -> collector 的认知传递
- state mismatch 导致页面模型刷新与重新规划
- contract violation 导致 repair flow，而非静默推断

### E2E 测试

- 列表页直接采集路径
- 分类页拆分后执行路径
- 登录/验证码人工接管路径
- 循环导航触发策略切换路径

## 结论

AutoSpider 的目标架构不是继续给现有流程拼更多节点，而是建立三项长期稳定能力：

1. 统一世界模型，保证认知连续体存在。
2. 建立分层控制，让计划、调度、执行、反馈各司其职。
3. 建立失败闭环，让系统不仅能成功沉淀规则，也能从失败中沉淀诊断知识。

当这三项能力建立后，系统才会从“能跑的采集链路”真正升级为“可修正、可学习、可持续演进的采集智能体”。
