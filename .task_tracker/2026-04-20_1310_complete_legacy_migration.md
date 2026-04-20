# Task Tracker

- **timestamp**: 2026-04-20 13:10 UTC+08:00
- **task**: 完成 active 代码对 `composition.legacy` 的迁移，消除 `src/autospider` 中剩余 legacy graph/pipeline/taskplane 直接依赖
- **status**: completed

## Constraints

- **language**: 中文回复
- **comments_policy**: 不新增或删除注释/文档，除非任务需要
- **task_tracking**: 执行前持久化计划；子任务完成后实时更新；完成后标记 completed
- **safety**: 不引入 silent fallback / mock；失败应显式暴露
- **metrics**: 函数 <= 50 行，文件 <= 300 行，嵌套 <= 3 层
- **deletion**: 不做硬删除；tracked 文件删除使用 git rm
- **branching**: 属于多文件大规模迁移，先创建隔离分支再继续
- **scope**: 仅迁移 `src/autospider` active 代码；测试会随行为变更更新，但不以清理全部 legacy 测试导入为前提

## Plan

1. [completed] 创建隔离分支并盘点 `src/autospider` 中剩余 active legacy 依赖
2. [completed] 将 `legacy/{graph,pipeline,taskplane,taskplane_adapter}` 的实现落到正式命名空间，并处理 `subgraphs.py` 等结构冲突
3. [completed] 修正 active 调用点与兼容层导入，清理 `src/autospider` 中剩余 direct legacy imports
4. [completed] 执行定向验证、更新状态与非测试代码增删行统计，并按原子提交规则提交

## Verification

- `rg -n "composition\\.legacy|_legacy_runtime" src/autospider --glob '!**/__pycache__/**'`：无命中
- import 烟测：`autospider.composition.graph.main_graph`、`runner`、`_multi_dispatch`、`composition.pipeline.{types,worker,finalization}`、`composition.taskplane_adapter.graph_integration` 全部导入成功
- `pytest tests/test_graph_runner.py tests/test_main_graph.py tests/test_execution_handoff.py tests/test_pipeline_runtime_integration.py tests/test_subtask_worker_runtime_payload.py -q -o cache_dir=artifacts/.pytest_cache`：`24 passed`

## Diff Stats

- **non_test_code_added**: 10108
- **non_test_code_deleted**: 96
