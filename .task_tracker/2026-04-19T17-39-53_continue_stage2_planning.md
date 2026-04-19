# Task Record

- Timestamp: 2026-04-19T17:39:53+08:00
- Task: 继续推进 refactor 阶段 2，优先完成 `2.C Planning`
- Status: in_progress

## User Constraints

- 默认用中文回复
- 不在最终回复末尾提出后续任务或增强建议
- 遵循 `refactor/` 中的阶段与分层约束
- 继续推进时要注意代码精简

## System and Repository Constraints

- 修改前先持久化任务时间与计划
- 不回退用户已有改动或中断残留改动
- 手工代码编辑必须使用 `apply_patch`
- 完成明显子任务后实时更新 `.task_tracker`
- 最终报告非测试文件新增/删除行数

## Plan

- [x] 盘点 `Planning` 旧实现与新骨架缺口
- [x] 迁入 `contexts/planning/domain/model.py`
- [x] 迁入 `contexts/planning/domain/policies.py`
- [x] 实现 `contexts/planning/application/use_cases/*`
- [x] 实现 `contexts/planning/infrastructure/repositories/artifact_store.py`
- [x] 补 `tests/contexts/planning/*`
- [x] 运行聚焦验证并更新状态

## Progress

- `Planning` 已落地最小主体：`domain/model.py`、`domain/policies.py`、`domain/ports.py`
- `Planning application` 已落地：`create_plan`、`decompose_plan`、`replan`、`classify_runtime_exception`、`handlers`
- `Planning infrastructure` 已落地：`repositories/artifact_store.py`
- `Collection domain` 已启动：新增 `domain/model.py`、`domain/services.py`、`domain/policies.py` 以及 `field/xpath/*` 纯函数模块
- `Chat` 中的弃用命名 `LegacyTaskClarifierAdapter` 已移出，统一为 `TaskClarifierAdapter`
- 已验证命令：
  - `ruff check src/autospider/contexts/planning src/autospider/contexts/collection tests/contexts/planning tests/contexts/collection`
  - `pytest tests/contexts/planning tests/contexts/collection/domain -q`
  - `ruff check src/autospider/contexts/chat src/autospider/contexts/planning src/autospider/contexts/collection tests/contexts tests/test_entry_nodes_runtime_handoff.py`
  - `pytest tests/contexts/chat/application/test_use_cases.py tests/test_entry_nodes_runtime_handoff.py tests/contexts/experience tests/contexts/planning tests/contexts/collection/domain -q`
