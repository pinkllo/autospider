# 0002 · Redis 同时承担消息队列与仓储

- 状态：Accepted
- 日期：2026-04-20
- 决策者：@pinkllo

## 背景

重构前存在持久化双轨：`common/db/`（SQLAlchemy）与 `common/storage/`（Redis + 文件）职责重叠，同一份运行时状态在两处同步，易出现不一致。同时消息通道 `common/channel/redis_channel.py` 又独立维护另一套 Redis key 命名习惯，三处散落使得整体 key 规范无法统一。

重构要求「单一事实源」与「可机器化校验的 key 规范」。

## 决策

- **持久化**：核心运行态（task plan、run artifact index、skill registry 等）统一以 Redis 作为主存储；关系型 DB（PostgreSQL）只保留长期审计与查询所需的历史数据，由 Alembic 管理 schema。
- **消息**：跨 context 的 Domain Event / Command 同样走 Redis（Streams/List 为主），与持久化使用同一连接池。
- **Key 规范**：集中注册在 `platform/persistence/redis/keys.py`，强制 `v1:` 版本前缀，禁止任何代码内手写 `f"autospider:..."`。
- **连接**：由 `platform/persistence/redis/` 统一暴露 `get_client()` 等工厂函数，业务层只依赖端口。

## 后果

- 正面：单一仓储与消息通道；key 命名集中可审计；减少依赖栈复杂度（去除文件存储的一条路径）。
- 负面：历史 checkpoint / Redis 数据不向下兼容；单点失败风险集中于 Redis，需要在部署层面关注高可用。
- 触发的后续工作：`03-contracts.md` 中的 Redis keys 章节；阶段 1 的 `redis key registry` 提交；ADR 0004 的 import-linter 契约（禁止跨 context 直接访问 Redis key 字面量）。

## 替代方案

- **继续 SQLAlchemy + Redis 双轨**：维持现状，无法解决一致性与散落问题，否决。
- **纯 DB 持久化 + 独立消息代理（如 Kafka/NATS）**：运维成本陡增，且当前规模未到该拐点，否决。
