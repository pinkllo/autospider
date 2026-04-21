# 0005 · 以 facade 冻结 contexts 边界并显式登记债务

- 状态：Accepted
- 日期：2026-04-21
- 决策者：@pinkllo

## 背景

现有 `contexts` 并不是顶层划分错误，而是内部边界已经失真：

- `collection` 留有 8 个 `sys.modules[__name__] = _impl` 包装模块；
- `planning.domain` 曾直接依赖 `collection.infrastructure`；
- `collection` 和 `planning` 内仍有少量 `contexts -> composition` 反向依赖；
- 原 `.importlinter` 直接要求 4 个 context 完全独立，但仓库现实已经演变为“跨 context 需要通过少量公开 facade 协作”。

继续维持“绝对独立”的配置只会得到一个长期失真的红灯，而不是可执行的边界契约。

## 决策

- 阶段 1 不再把“4 个 context 绝对独立”当作立即可执行的规则。
- 改为冻结一份机器可读的边界基线：
  `refactor/_generated/context-boundaries-phase1.json`
- 公开协作统一收口到 context facade：
  `autospider.contexts.chat`
  `autospider.contexts.planning`
  `autospider.contexts.collection`
  `autospider.contexts.experience`
- `.importlinter` 只保留当前能真实执行的规则：
  - `domain` 外部依赖纯净
  - `chat` / `experience` 的 application 不依赖本 context infrastructure
  - `collection` 与 `planning` 对外只能通过顶层 facade 引用对方 context
  - `contexts -> composition` backedge 先显式豁免，等待阶段 2/3 消除
- 剩余无法当场移除的债务必须登记到基线文件，并由合同测试冻结。

## 后果

- 正面：
  - 边界规则从“理想化配置”变成“当前可验证的约束”；
  - 后续阶段可以围绕一份稳定的 ownership/import map 迁移，不再反复摇摆；
  - 新增跨 context 深层 import 会被 import-linter 和合同测试双重阻止。
- 负面：
  - 阶段 1 接受少量显式例外仍然存在，例如 `planning.infrastructure.adapters.task_planner -> collection.domain.variant_resolver`；
  - `contexts -> composition` 反向依赖暂未在本阶段清零，只是被固定为显式债务。

## 替代方案

- 继续保留 `contexts-isolated` 的绝对独立契约：
  不能反映当前真实依赖，否决。
- 直接开始搬迁实现文件：
  没有统一 import map，会在阶段 2/3 反复搬家，否决。
