# Task Record

- Timestamp: 2026-04-19T19:11:53+08:00
- Task: 将当前分支已暂存的阶段 2（Chat/Experience/Planning/Collection-domain）改动切成一组原子 commit
- Status: completed

## User Constraints

- 默认用中文回复
- 不在最终回复末尾提出后续任务或增强建议
- 严格遵循 `refactor/04-execution-plan.md` 的 commit 边界与 ≤800 行（纯搬家 ≤1500）约束
- 每个 commit 自包含、测试绿
- 不引入 silent fallback、mock 成功路径或防御性兜底
- 弃用部分要移出项目

## System and Repository Constraints

- 修改前先持久化任务时间与计划
- Git 跟踪文件删除使用 `git rm`
- 未跟踪文件不硬删，移入 `.task_trash/`
- 完成明显子任务后实时更新 `.task_tracker`
- 最终报告非测试文件新增/删除行数
- 已在 `refactor-stage2-planning-cleanup` 分支作业，本次不做新分支

## Current Staged Snapshot

- 162 个条目 / 5967 insertions / 2932 deletions
- 覆盖：Chat 全部、Experience 全部、Planning 全部（旧实现已 `git rm`）、Collection 仅 domain 骨架
- `artifacts/` 为未跟踪运行产物，本轮不入提交

## Commit Slice Plan (Route C — compressed to 2 commits)

选择背景：工作区已一次性完成所有 Context 的 import 切换与旧文件删除，全仓无指向旧路径的残留引用，
按原计划逐 Context 切片需要为多个跨 Context 共享文件（`domain/__init__.py`、`pipeline/finalization.py`、
`pipeline/runner.py`、`pipeline/orchestration.py`、`graph/nodes/entry_nodes.py` 等）写中间态并反复覆盖/
复位，执行成本高且无法为每个中间 commit 独立跑 pytest。经用户确认，采用路线 C。

1. **c1 `chore(task-tracker): persist stage-2 progress records`**
   - `.task_tracker/*.md` × 8（含本文件）
   - 纯文档记录，不影响源码
2. **c2 `refactor(stage2): migrate chat/experience/planning bounded contexts; scaffold collection domain`**
   - 覆盖所有阶段 2 改动：contexts/{chat,experience,planning,collection}/** 新增 + 旧
     `domain/{chat,planning}.py`、`graph/failures.py`、`common/experience/**` 删除 + 所有 callers
     import 切换
   - 规模：约 5967 insertions / 2932 deletions，162 个条目
   - **明确标注违反 `refactor/04-execution-plan.md §0.1` 的 ≤800 行硬限**，原因：工作区迁移已一次性完成，
     拆分需写中间态文件且无法中间验证，综合成本高于收益。Commit message 完整陈述 scope 与理由。

## Verification

- 提交后：`ruff check src tests`
- 提交后：`pytest -m smoke -q`
- 提交后：`pytest tests/contexts -q`（按新 context 的测试目录聚合）
- 若验证失败，`git reset --soft HEAD^` 回到暂存状态再修复

## Progress

- [x] 持久化切片计划
- [x] c1 task_tracker 记录 commit — `bea9447`
- [x] c2 阶段 2 聚合 migration commit — `44b2762`
- [x] 聚合验证：ruff baseline 对比（pre-refactor 125 → post-refactor 112，不增不降为负数）；`pytest -m smoke` 2 处 pre-existing 失败，与本 commit 无关；`pytest tests/contexts -q` 46 通过

## Line Stats (non-test, 非测试文件)

- c2 `src/**`: 112 files changed, 4158 insertions(+), 2917 deletions(-)
- c2 `tests/**`（仅供参考，统计排除）: 43 files changed, 1536 insertions(+), 15 deletions(-)
- 非测试净新增：+1241 行
- 清理工作室中临时复位产生的文件已移入 `.task_trash/2026-04-19T19-11-53_accidental_restore/`

## Risks

- c2 单 commit 5700+ 行，严重超 refactor 计划的 ≤800 行硬限；用户已事先同意并接受这一例外，按"显式 + 文档化"的要求，commit message 需完整陈述原因与未来补救策略
- `artifacts/` 目录未跟踪，本轮不入提交
- 后续如需继续阶段 2.C/2.D 剩余收口（`crawler/planner/` 未删、Collection application/infra 未落地），新 commit 须回到 ≤800 行硬限范围内
