# 0001 · 采用轻量 DDD 作为架构取向

- 状态：Accepted
- 日期：2026-04-20
- 决策者：@pinkllo

## 背景

`src/autospider/` 约 41k LoC、178 个 `.py`，长期按技术分层组织（`graph/`、`pipeline/`、`crawler/`、`field/`、`common/`），职责散落、跨模块耦合严重：

- `domain/` 存在但非唯一事实源；业务状态散落在 `graph/`、`pipeline/`、`crawler/planner/`、`common/`。
- `common/` 同时承担 `browser/`、`channel/`、`db/`、`experience/`、`llm/`、`som/`、`storage/`、`utils/` 等异质职责，演变为基础设施袋。
- `graph/runner.py` 与 `pipeline/runner.py`、`pipeline/orchestration.py` 并存，编排层重叠。
- 导入环征兆（`cli.py` 以 `_CliRuntimeProxy` 惰性加载规避）。

继续以技术分层维护成本过高，且难以隔离核心领域规则。

## 决策

采用「轻量 DDD」作为新骨架：

- **Bounded Context**：按业务维度切出 `chat`、`planning`、`collection`、`experience` 四个上下文。
- **分层**：`interface` → `composition` → `contexts.*.{application,domain,infrastructure}` → `platform`。
- **构件**：Aggregate、Value Object、Domain Service、Application Service、Repository、Domain Event。
- **依赖方向**：`domain` 不依赖任何外部库；`application` 不依赖 `infrastructure`；`interface` 不直接依赖 `contexts`。

## 后果

- 正面：核心规则可测、可演化；跨 context 通过事件与 saga 解耦；`import-linter` 可机器化守护分层。
- 负面：新增文件数量明显上升；旧代码需要分阶段迁移，存在较长过渡期。
- 触发的后续工作：ADR 0002/0003/0004、阶段 1~5 执行计划、`refactor/05-guardrails.md` 中的 CI/防腐配置。

## 替代方案

- **保持技术分层继续打补丁**：成本随时间复利增长，已经出现导入环与编排重叠，否决。
- **微服务拆分**：单体项目、单一部署形态、无外部消费者，微服务引入运维成本收益不成比例，否决。
- **Clean Architecture 严格版**：对当前体量与团队规模过重，采用轻量 DDD 折中。
