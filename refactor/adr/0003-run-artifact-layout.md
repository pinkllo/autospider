# 0003 · 运行产物统一为 output/runs/<run_id>/ 布局

- 状态：Accepted
- 日期：2026-04-20
- 决策者：@pinkllo

## 背景

重构前产物散落：`output/`、`artifacts/`、`src/output/`、`screenshots/`、`tests/benchmark/reports/` 等多处并存；不同子系统各自生成结构，导致：

- 运行失败时缺乏一站式现场；
- 测试与真实运行产物混在同一目录；
- CI / 离线评估需要按子系统拼装路径。

## 决策

- **根路径**：所有正式运行产物统一落盘到 `output/runs/<run_id>/`。
- **`run_id`**：由 `platform/shared_kernel` 的 ID 工厂生成，且贯穿 `trace_id` / 日志 / 事件。
- **子目录约定**：
  - `artifacts/`：页面快照、截图、抓取结果等二进制/文本产物
  - `logs/`：结构化日志
  - `events/`：领域事件归档
  - `result.json`：本次运行的最终 `ResultEnvelope[T]`
- **测试产物**：测试专用临时目录落到 `artifacts/test_tmp/`，并在 `.gitignore` 中忽略。
- **向下兼容**：不保留旧目录约定；阶段 1 之后历史 run 不再可解析。

## 后果

- 正面：一个 `run_id` 即可定位全部现场；便于归档、清理、离线评估；CI 产物收集路径单一。
- 负面：历史脚本/工具（依赖旧路径）需要同步迁移；跨 run 共享的全局产物需要另寻位置。
- 触发的后续工作：`03-contracts.md` 的 Artifacts / ResultEnvelope 章节；阶段 1 的 `platform.observability` 与 `platform.persistence.filesystem`。

## 替代方案

- **按 context 分别落盘**：跨 context 聚合时仍需拼装路径，失去统一入口，否决。
- **只在日志中写索引、产物保留旧目录**：索引与实体分离增加理解成本，否决。
