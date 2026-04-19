# Task Record

- Timestamp: 2026-04-19T22:03:11+08:00
- Task: 继续推进阶段 2，迁移 Collection Context 的 adapter 层并归档已切走的旧实现
- Status: completed 2026-04-19T22:19:00+08:00

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
- 报告非测试文件新增/删除行数，排除测试文件
- 当前分支：`refactor-stage2-planning-cleanup`

## Execution Plan

1. 迁移 `crawler/collector/llm_decision.py` 到 `contexts/collection/infrastructure/adapters/`
2. 将已切走调用点的旧 `llm_decision.py`、`field_xpath_query_service.py`、`field_xpath_write_service.py` 归档到 `.task_trash/`
3. 继续拆分并迁移 `crawler/output/script_generator.py` 到 collection adapter
4. 更新验证、任务记录与行数统计

## Progress

- [x] 持久化本轮任务记录
- [x] 新增 `contexts/collection/infrastructure/adapters/{__init__,_llm_shared,_llm_decision,_llm_pagination,llm_navigator}.py`
- [x] 更新 `crawler/collector/__init__.py`、`crawler/collector/pagination_handler.py`、`tests/test_decision_context_wiring.py`
- [x] 归档旧 `field_xpath_query_service.py` / `field_xpath_write_service.py` / `llm_decision.py` 到 `.task_trash/stage2_collection_archive/`
- [x] `ruff check` 覆盖 adapter 迁移相关文件通过
- [x] `pytest -q tests\\test_decision_context_wiring.py tests\\contexts\\collection\\infrastructure\\test_collection_repositories.py` 通过（7 passed）
- [x] 新增 `contexts/collection/infrastructure/adapters/{_scrapy_script_template,scrapy_generator}.py`
- [x] 更新 `crawler/explore/url_collector.py` 到新 `scrapy_generator` 路径
- [x] 为 `scrapy_generator` 补充 2 条基础测试
- [x] 归档旧 `crawler/output/script_generator.py` 到 `.task_trash/stage2_collection_archive/`

## Verification

- `ruff check` 覆盖 `collection` adapter 与相关测试文件通过
- `pytest -q tests\\test_decision_context_wiring.py tests\\contexts\\collection\\infrastructure\\test_collection_repositories.py` 通过（7 passed）
- `rg -n "crawler\\.collector\\.llm_decision|field_xpath_query_service|field_xpath_write_service|crawler\\.output\\.script_generator" src tests .task_trash` 仅剩 `.task_trash/` 归档文件与新实现

## Line Stats

- 非测试文件：+556 / -7
