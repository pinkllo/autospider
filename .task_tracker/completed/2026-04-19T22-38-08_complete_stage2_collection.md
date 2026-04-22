# Task Record

- Timestamp: 2026-04-19T22:38:08+08:00
- Task: 将阶段 2 未完成的部分完成
- Status: completed

## User Constraints

- 默认用中文回复
- 不在最终回复末尾提出后续任务或增强建议
- 一次推进多一点
- 若旧文件删不掉，可移到 `.task_trash/`
- 不引入 silent fallback、mock 成功路径或防御性兜底

## System and Repository Constraints

- 修改前先持久化任务时间与计划
- 完成子任务后实时更新 `.task_tracker`
- 手工代码编辑必须使用 `apply_patch`
- 删除 Git 跟踪文件时优先使用 `git rm`；删不掉或不适合直接删时移到 `.task_trash/`
- 保持原子提交并使用 Conventional Commits
- 完成后报告非测试文件新增/删除行数，排除测试文件
- 当前分支：`refactor-stage2-planning-cleanup`

## Execution Plan

1. 盘点 Collection Context 剩余缺口，确定 application / infrastructure / wiring 的最小收口路径
2. 新增 `contexts/collection/application/use_cases/*` 与缺失的 repository / adapter 文件
3. 将 `pipeline` / `crawler` / `field` 中仍在承担 Collection 职责的入口切换到新 use case
4. 归档已被替代的旧 Collection 实现到 `.task_trash/stage2_collection_archive/`
5. 运行静态检查与针对性测试，更新任务记录与非测试行数统计

## Progress

- [x] 持久化本轮任务记录
- [x] 盘点 Collection 缺口并确定收口路径
- [x] 新增 Collection application/use_cases 与剩余 infrastructure 文件
- [x] 切换旧入口到新 Collection use case
- [x] 通过 `git mv` 将 Collection 主实现迁入 `contexts/collection/`，旧路径改为模块别名兼容层
- [x] `ruff check` 覆盖新 Collection use case / repository / adapter / wiring 通过
- [x] `pytest -q tests/test_decision_context_wiring.py tests/crawler/collector/test_navigation_handler_replay.py tests/crawler/collector/test_url_extractor_restore.py tests/contexts/collection/infrastructure/test_collection_repositories.py` 通过（12 passed）
- [x] `pytest -q tests/test_subtask_worker_runtime_payload.py tests/test_pipeline_runtime_integration.py` 通过（13 passed）
- [x] 统计非测试文件增删行并完成提交/标记

## Verification

- `ruff check` 覆盖 Collection 迁移文件与接线文件通过
- `pytest -q tests/test_decision_context_wiring.py tests/crawler/collector/test_navigation_handler_replay.py tests/crawler/collector/test_url_extractor_restore.py tests/contexts/collection/infrastructure/test_collection_repositories.py` 通过（12 passed）
- `pytest -q tests/test_subtask_worker_runtime_payload.py tests/test_pipeline_runtime_integration.py` 通过（13 passed）

## Line Stats

- 非测试文件：+3890 / -3543
