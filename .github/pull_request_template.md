## 摘要
<!-- 本 PR 做了什么变更 -->

## 架构影响
- [ ] 新增/删除 Bounded Context
- [ ] 修改 `contexts/*/domain/` 下的聚合/值对象
- [ ] 新增/删除 Domain Event
- [ ] 修改 Redis key 规范（bump version?）
- [ ] 修改 DB schema（含 Alembic migration?）
- [ ] 修改 `ResultEnvelope` / 产物格式
- [ ] 以上都没有

## 验证
- [ ] `scripts/verify.ps1` 本地绿
- [ ] `pytest tests/contracts -q` 快照无破坏（或已更新并说明原因）
- [ ] CI 绿

## ADR
若涉及架构决策变更，请附上对应 `refactor/adr/NNNN-*.md` 的链接。

## 回滚方案
<!-- 如何回滚本 PR -->
