# 0004 · 以 import-linter 机器化守护分层契约

- 状态：Accepted
- 日期：2026-04-20
- 决策者：@pinkllo

## 背景

ADR 0001 选择了轻量 DDD，但仅靠 code review 无法持续保证：

- `domain` 纯净（不引入 `langgraph` / `playwright` / `redis` / `sqlalchemy` / `openai` / `langchain` / `loguru` 等）；
- `application` 不依赖 `infrastructure`；
- `interface` 不直接依赖 `contexts`；
- 4 个 Bounded Context 相互独立；
- 分层方向（`interface → composition → contexts → platform`）不被反向依赖破坏。

一旦放任随手 import，「轻量 DDD」会在几次迭代后退化回原样。

## 决策

- 采用 [`import-linter`](https://github.com/seddonym/import-linter) 在 CI 与 pre-commit 中强制下列 5 条契约（详见项目根 `.importlinter`）：
  1. **Layered architecture**：`interface → composition → contexts → platform` 单向依赖，`platform.shared_kernel` 可被任何层使用。
  2. **Bounded contexts isolated**：4 个 context 相互独立。
  3. **Domain pure**：各 context 的 `domain` 禁止 import `langgraph` / `playwright` / `redis` / `sqlalchemy` / `openai` / `langchain` / `loguru` 等外部依赖。
  4. **Application not importing infrastructure**：同一 context 内 `application` 不依赖 `infrastructure`。
  5. **Interface via composition**：`interface` 不直接依赖 `contexts`。
- 违规即 CI 失败；过渡期对 `autospider.legacy.*` 整块 `ignore_imports`，完成物理删除后移除豁免。
- 新增 / 调整契约必须伴随新 ADR（本 ADR 模板中的「ADR 必写场景 5」）。

## 后果

- 正面：分层违规在开发期即被捕获；review 负担下降；`domain` 的可移植性有机械保证。
- 负面：初期会触发大量既有代码违规，需要分阶段处理；legacy 豁免是技术债务，需要显式清理时机。
- 触发的后续工作：阶段 5 的 `commit[5.1]` 落地 `.importlinter`、`pre-commit` 与 CI；阶段 4 完成物理删除后移除 legacy 豁免。

## 替代方案

- **仅靠 code review**：规模增大后无法稳定执行，否决。
- **以目录结构 + 自写脚本校验**：实现成本高且难以覆盖 forbidden / independence 两类契约，否决。
