# Task Record

- Timestamp: 2026-04-19T21:18:07+08:00
- Task: 继续推进阶段 2，迁移 Collection Context 的配置/进度持久化到 `contexts/collection/infrastructure/repositories`
- Status: completed 2026-04-19T21:36:00+08:00

## User Constraints

- 默认用中文回复
- 不在最终回复末尾提出后续任务或增强建议
- 继续推进 `refactor/04-execution-plan.md` 的阶段 2
- 不引入 silent fallback、mock 成功路径或防御性兜底

## System and Repository Constraints

- 修改前先持久化任务时间与计划
- 完成子任务后实时更新 `.task_tracker`
- 手工代码编辑必须使用 `apply_patch`
- Git 跟踪文件删除需使用 `git rm`
- 报告非测试文件新增/删除行数，排除测试文件
- 当前分支：`refactor-stage2-planning-cleanup`
- 单次提交保持原子，优先控制在阶段计划的 diff 硬限内

## Baseline

- 阶段 2 的 Planning 拆分已新增 `a6f003c`
- `contexts/collection/infrastructure/repositories/` 仍为空壳
- 旧 `common/storage/collection_persistence.py` 仍被 `crawler/`、`pipeline/`、`graph/` 多处引用

## Execution Plan

1. 新建 `config_repository.py` / `progress_repository.py`，接收旧 `collection_persistence.py` 的职责
2. 更新 `crawler/`、`pipeline/`、`graph/` 的导入路径
3. 删除旧 `common/storage/collection_persistence.py` 并清理 `common/storage/__init__.py`
4. 运行针对性静态检查/测试，更新任务记录与行数统计

## Progress

- [x] 持久化本轮任务记录
- [x] 新增 `contexts/collection/infrastructure/repositories/{__init__,config_repository,progress_repository}.py`
- [x] 切换 `crawler/base`、`crawler/batch`、`crawler/explore`、`crawler/output`、`graph/nodes`、`pipeline/helpers` 的导入路径
- [x] 使用 `git rm` 删除旧 `src/autospider/common/storage/collection_persistence.py`
- [x] 精简 `src/autospider/common/storage/__init__.py`，去掉旧 collection persistence 导出
- [x] 新增 `tests/contexts/collection/infrastructure/test_collection_repositories.py`

## Verification

- `python -m compileall` 覆盖本轮迁移相关文件通过
- `ruff check src/autospider/contexts/collection/infrastructure/repositories tests/contexts/collection/infrastructure/test_collection_repositories.py` 通过
- `pytest -q tests\\contexts\\collection\\infrastructure\\test_collection_repositories.py` 通过（2 passed）
- `rg -n "common\\.storage\\.collection_persistence" src tests` 无剩余引用

## Line Stats

- 非测试文件：+291 / -281
