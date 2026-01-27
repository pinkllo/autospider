# LLM 解析与规划 (LLM)

`llm` 模块封装了与多模态大模型的交互逻辑，实现了基于 SoM 观察结果的决策和规划。

---

## 📁 核心文件

- `decider.py`: 负责执行具体的单步动作决策（Observe -> Decide）。
- `planner.py`: 负责整体任务的宏观规划和步骤拆解。
- `prompt_template.py`: 统一管理各种任务类型的 Prompt 模板。

---

## 🚀 决策流程

系统采用 **Visualize -> Reasoning -> Act** 的三段式逻辑：
1. **Visualize**: 将 SoM 标注后的截图和简化的 DOM 树传给模型。
2. **Reasoning**: 模型分析当前页面状态，在 `thinking` 字段输出思考过程。
3. **Act**: 输出符合 `ProtocolMessage` 规范的动作指令。

---

*最后更新: 2026-01-27*
