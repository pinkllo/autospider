# AutoSpider 重构方案（索引）

本目录收录 AutoSpider 从"打补丁式单体"向"轻量 DDD + 模块化单体"演进的完整方案。**仅为方案文档，本次不包含任何源代码改动**。所有变更以本地 commit 方式推进、可随时 `git reset --hard` 回滚，默认不向远端推送。

---

## 一句话概括

以 **Bounded Context** 切分 41k LoC / 178 文件的代码库，采用轻量 DDD（Aggregate + Domain Service + Repository + Domain Event），Redis 同时承担仓储与消息队列，产物/日志收敛为 `run_id` 粒度的统一目录与 `ResultEnvelope`，全过程以可回滚的 local commit 串行推进。

---

## 锁定的决策（v2 已确认，不再讨论）

| 项 | 决策 |
|---|---|
| 架构取向 | **轻量 DDD**：Bounded Context + Aggregate + Domain Service + Application Service + Repository + Domain Event |
| 包名 | **保持 `autospider`** |
| 兼容性 | 无外部消费者，**不留 shim / `@deprecated` / `legacy/`**，旧 import 路径直接删除 |
| DB schema | **重新设计**，丢弃开发数据，Alembic 初始迁移 |
| Redis key | **重新设计**命名规范，`v1:` 版本前缀，集中注册，同时承担持久化 + 消息队列 |
| 产物格式 | **统一为 `output/runs/<run_id>/` 结构** |
| 可观测性 | 结构化日志 + `trace_id` / `run_id` `contextvars` 贯穿 + 统一 `ResultEnvelope[T]` |
| 提交策略 | 每步 **local `git commit`**，每阶段末打 tag；**不 `git push`**；单 commit diff ≤ 800 行 |
| 测试安全网 | 先补「端到端契约快照」后再做大手术 |

---

## 文档导读（建议按顺序读）

| # | 文件 | 作用 | 何时看 |
|---|---|---|---|
| 01 | [`01-architecture.md`](./01-architecture.md) | 目标架构：Bounded Context、聚合、分层、依赖规则、目录树 | 理解最终形态 |
| 02 | [`02-migration-map.md`](./02-migration-map.md) | 旧 → 新 文件映射表 + 巨石文件拆分清单 + 删除清单 | 具体迁移谁到哪 |
| 03 | [`03-contracts.md`](./03-contracts.md) | DB schema / Redis keys / Messaging / Saga / Observability / Artifacts / ResultEnvelope | 设计新契约时查 |
| 04 | [`04-execution-plan.md`](./04-execution-plan.md) | 5 阶段、~25 个 commit 的详细执行清单（含验证命令与回滚） | 真正动手时查 |
| 05 | [`05-guardrails.md`](./05-guardrails.md) | `import-linter`、`ruff`、`mypy --strict`、`pre-commit`、CI 配置样例 | 防止再次"打补丁" |

---

## 阶段快照（详见 04）

| 阶段 | 目标 | commit 数 | tag |
|---|---|---|---|
| **0** | 契约快照安全网（纯新增） | 2 | `refactor-phase-0` |
| **1** | 骨架 + 新 DB schema + Redis key registry + 日志基建 | 5 | `refactor-phase-1` |
| **2** | 4 个 Bounded Context 逐个迁入（每 Context ≈ 5 commit） | 15~20 | `refactor-phase-2` |
| **3** | Messaging + Saga + LangGraph 主图重写 | 3 | `refactor-phase-3` |
| **4** | 物理删除旧包 + 死代码扫除 | 2 | `refactor-phase-4` |
| **5** | CI/防腐 + 文档 + ADR | 2 | `refactor-phase-5` |

---

## 现状速览（诊断）

- **规模**：`src/autospider/` 178 个 `.py` ≈ **41k LoC**；10+ 个文件 >800 行。
- **分层漏层**：`domain/` 存在但非唯一事实源；业务状态散落在 `graph/`、`pipeline/`、`crawler/planner/`、`common/` 多处。
- **`common/` 变基础设施袋**：同时含 `browser/`、`channel/`、`db/`、`experience/`、`llm/`、`som/`、`storage/`、`utils/` + 多个顶层杂项。
- **持久化双轨**：`common/db/` (SQLAlchemy) vs `common/storage/` (Redis + 文件) 职责重叠。
- **编排层重叠**：`graph/runner.py` & `graph/main_graph.py` & `pipeline/runner.py` & `pipeline/orchestration.py` 并存。
- **两套 taskplane**：`taskplane/` 与 `taskplane_adapter/` 并存。
- **导入环征兆**：`cli.py` 用 `_CliRuntimeProxy` 惰性加载规避环。
- **测试迁移半途**：40+ 扁平测试，`tests/autospider_next/` 与 `tests/unit/` 空壳。

---

## 风险提示

- 本方案**不保证** checkpoint / Redis 数据向下兼容。执行阶段 1 之后，历史 run 无法 resume（未上线可接受）。
- 巨石文件拆分风险最高，阶段 2 严格遵守「抽函数→改签名→搬文件」三步法，每步独立 commit。
- Playwright/LLM 无法在 CI 稳定跑 → 契约快照测试用 mock LLM + 本地 Playwright；E2E 走独立 workflow。

---

## 下一步

1. 阅读 01~05 文件，**对任何不同意之处先开 issue/便签反馈**，不要直接改源码。
2. 确认无异议后，按 [`04-execution-plan.md`](./04-execution-plan.md) **从 commit[0.1] 开始**。
3. 每个 commit 完成后跑 `scripts/verify.ps1`（在 commit[0.2] 中创建）。
