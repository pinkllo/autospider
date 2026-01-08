# llm_decision.py - LLM 决策模块

llm_decision.py 模块提供 LLM 决策制定功能，负责调用 LLM 进行决策。

---

## 📁 文件路径

```
src/autospider/extractor/collector/llm_decision.py
```

---

## 📑 函数目录

### 🚀 核心类
- `LLMDecisionMaker` - LLM 决策制定器主类

### 🔧 主要方法
- `ask_for_decision()` - 让视觉 LLM 决定如何获取详情页 URL

---

## 🚀 核心功能

### LLMDecisionMaker

LLM 决策制定器，负责调用 LLM 进行决策。

```python
from autospider.extractor.collector.llm_decision import LLMDecisionMaker

# 创建 LLM 决策制定器
decision_maker = LLMDecisionMaker(
    page=page,
    decider=decider,
    task_description="收集商品详情页链接",
    collected_urls=[],
    visited_detail_urls=set(),
    list_url="https://example.com/list"
)

# 让视觉 LLM 决定
decision = await decision_maker.ask_for_decision(
    snapshot=snapshot,
    screenshot_base64=screenshot_base64
)

print(f"决策类型: {decision.get('action')}")
print(f"理由: {decision.get('reasoning')}")
```

---

## 💡 特性说明

### 多模态决策

结合页面截图和元素信息进行决策：

```python
# 构建消息内容
message_content = self._build_message_content(
    snapshot,
    screenshot_base64,
    validation_feedback
)

# 调用 LLM
response = await self.llm.ainvoke(messages)
```

---

## 🔧 使用示例

### 基本使用

```python
from autospider.extractor.collector.llm_decision import LLMDecisionMaker

# 创建 LLM 决策制定器
decision_maker = LLMDecisionMaker(
    page=page,
    decider=decider,
    task_description="收集商品详情页链接",
    collected_urls=[],
    visited_detail_urls=set(),
    list_url="https://example.com/list"
)

# 让视觉 LLM 决定
decision = await decision_maker.ask_for_decision(
    snapshot=snapshot,
    screenshot_base64=screenshot_base64
)

print(f"决策: {decision}")
```

---

## 📚 方法参考

### LLMDecisionMaker 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `ask_for_decision()` | snapshot, screenshot_base64, validation_feedback | dict \| None | 让视觉 LLM 决定如何获取详情页 URL |

---

*最后更新: 2026-01-08*
