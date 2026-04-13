# AutoSpider Human-Centered Agent Strategy Design

**日期：** 2026-04-12

## 目的

这份补充说明用于把 2026-04-12 的人本智能体策略设计与当前 worktree 中已经落地的 Task 1-4 行为对齐，避免 README、设计文档和实际运行语义继续漂移。

## 当前公开执行链路

当前公开 CLI 入口只保留：

- `autospider chat-pipeline`
- `autospider resume`
- `autospider db-init`

其中真正的采集入口只有 `chat-pipeline`。chat 发起的任务在本分支中的执行主链路为：

```text
chat_clarify
-> chat_history_match
-> chat_review_task
-> chat_prepare_execution_handoff
-> plan_node
-> multi_dispatch_subgraph
-> monitor_dispatch_node
-> update_world_model_node
-> (按需回跳 plan_strategy_node 重新规划)
-> aggregate_node
```

这意味着当前系统是明确的 planning-first chat pipeline，并且执行期允许基于分发反馈进行重规划；它不是文档中曾经混用的多入口、多流水线对外模式。

## Grouped Collection 语义

### `group_by=category`

- 当澄清结果进入 `group_by=category` 时，系统把“分类”视为一级调度语义，而不是一个普通详情字段。
- planner 必须围绕分类导航结构生成分组子任务。
- dispatch / execution / aggregation 都以该分组语义为事实来源。

### `per_group_target_count`

- `per_group_target_count` 表示每个分类的目标采集数。
- 它不是所有分类共享的全局总上限。
- 如果最终发现 5 个分类且 `per_group_target_count=3`，调度目标是按 5 个分组分别执行，每组目标 3 条。

### 分类来源

- 分类集合应由页面事实发现。
- planner 在页面分析、导航结构与页面证据中识别可采集分类。
- `category_examples` 只作为语义提示或示例，不应替代页面发现结果。
- 只有在明确提供 `requested_categories` 时，系统才进入手工限定的分类范围。

### 分类字段产出

- 进入子任务执行后，输出记录中的分类值来自 subtask 的 `scope` / `fixed_fields`。
- 执行层不应把详情页里偶然出现的分类文字当成更高优先级事实。
- 这样可以保证“所属分类”等字段与调度时绑定的分类范围一致，避免详情页缺失、别名、面包屑抖动带来的错误归类。

## History Reuse 与语义身份

- 历史任务复用由 `semantic_signature` 驱动。
- `semantic_signature` 基于归一化后的 strategy payload 与字段集合生成。
- 分组语义中的 `group_by`、`per_group_target_count`、`category_discovery_mode`、`requested_categories`、`category_examples` 都属于身份的一部分。
- 因此，“按分类各抓 3 条”和“全站抓总计 3 条”不能复用同一语义身份。

## 文档同步要求

README 与 README_en 需要保持以下事实一致：

- 不再把 `multi-pipeline` 等旧能力写成公开主命令。
- 明确对外公开命令面只有 `chat-pipeline`、`resume`、`db-init`。
- 明确 chat 主链路是 planning-first。
- 明确 grouped collection 的分类来自页面发现。
- 明确分类字段来自 subtask scope / fixed fields，而不是详情页猜测。

## 非目标

- 本补充说明不引入新的 fallback、边界规则或静默降级。
- 本补充说明不修改 Task 1-4 已接受的运行时行为。
- 本补充说明只用于让文档语义与当前代码语义对齐。
