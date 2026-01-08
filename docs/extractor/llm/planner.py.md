# planner.py - 任务规划器

planner.py 模块提供任务规划功能，在执行前分析任务并生成执行计划。

---

## 📁 文件路径

```
src/autospider/extractor/llm/planner.py
```

---

## 📑 函数目录

### 🚀 核心类
- `TaskPlan` - 任务执行计划数据模型
- `TaskPlanner` - 任务规划器主类

### 🔧 主要方法
- `plan()` - 分析任务并生成执行计划

### 🔍 内部方法
- `_parse_response()` - 解析 LLM 响应

---

## 🚀 核心功能

### TaskPlan

任务执行计划数据模型，包含任务分析、执行步骤、目标描述等信息。

```python
from autospider.extractor.llm.planner import TaskPlan

# 创建任务计划
plan = TaskPlan(
    task_analysis="需要导航到商品列表页，然后进入商品详情页提取价格信息",
    steps=[
        "导航到商品列表页",
        "查找商品链接",
        "点击进入商品详情页",
        "提取价格信息",
        "返回结果"
    ],
    target_description="找到商品的价格信息",
    success_criteria="成功提取到商品价格",
    potential_challenges=[
        "商品列表可能有多页",
        "价格信息可能在不同的位置"
    ]
)

print(f"任务分析: {plan.task_analysis}")
print(f"执行步骤: {len(plan.steps)} 步")
```

### TaskPlanner

任务规划器，使用 LLM 分析任务并生成执行计划。

```python
from autospider.extractor.llm.planner import TaskPlanner

# 创建任务规划器
planner = TaskPlanner()

# 分析任务并生成执行计划
plan = await planner.plan(
    start_url="https://example.com/products",
    task="收集所有商品的价格信息",
    target_text="价格"
)

print(f"任务分析: {plan.task_analysis}")
print(f"执行步骤:")
for i, step in enumerate(plan.steps, 1):
    print(f"  {i}. {step}")
print(f"目标描述: {plan.target_description}")
print(f"成功标准: {plan.success_criteria}")
```

---

## 💡 特性说明

### LLM 驱动的任务分析

使用 LLM 分析任务并生成详细的执行计划：

```python
# 使用模板引擎加载和渲染 prompt
system_prompt = render_template(
    PROMPT_TEMPLATE_PATH,
    section="system_prompt",
)

user_prompt = render_template(
    PROMPT_TEMPLATE_PATH,
    section="user_prompt",
    variables={
        "start_url": start_url,
        "task": task,
        "target_text": target_text,
    }
)

# 调用 LLM 生成计划
response = await self.llm.ainvoke(messages)
plan = self._parse_response(response.content, task, target_text)
```

### 灵活的配置支持

支持多种配置方式：

```python
# 方式 1: 使用默认配置
planner = TaskPlanner()

# 方式 2: 自定义 API Key
planner = TaskPlanner(api_key="your-api-key")

# 方式 3: 完全自定义
planner = TaskPlanner(
    api_key="your-api-key",
    api_base="https://api.example.com/v1",
    model="gpt-4-vision"
)
```

### 配置优先级

配置优先级：参数 > planner 专用配置 > 主配置

```python
# 优先使用参数
self.api_key = api_key or config.llm.planner_api_key or config.llm.api_key
self.api_base = api_base or config.llm.planner_api_base or config.llm.api_base
self.model = model or config.llm.planner_model or config.llm.model
```

### 响应解析与容错

自动解析 LLM 响应，并提供默认计划作为容错：

```python
def _parse_response(self, response_text: str, task: str, target_text: str) -> TaskPlan:
    """解析LLM响应"""
    # 清理 markdown 代码块
    code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', cleaned_text)
    
    # 提取 JSON
    json_match = re.search(r'\{[\s\S]*\}', cleaned_text)
    
    # 解析失败，返回默认计划
    return TaskPlan(
        task_analysis=task,
        steps=["导航到目标页面", "查找并点击相关链接", "定位目标内容", "提取目标文本"],
        target_description=f"找到包含「{target_text}」的内容",
        success_criteria=f"页面中出现「{target_text}」",
        potential_challenges=["页面结构可能复杂", "可能需要多次点击"],
    )
```

---

## 🔧 使用示例

### 基本使用

```python
import asyncio
from autospider.extractor.llm.planner import TaskPlanner

async def plan_task():
    # 创建任务规划器
    planner = TaskPlanner()

    # 分析任务并生成执行计划
    plan = await planner.plan(
        start_url="https://example.com/products",
        task="收集所有商品的价格信息",
        target_text="价格"
    )

    print(f"任务分析: {plan.task_analysis}")
    print(f"\n执行步骤:")
    for i, step in enumerate(plan.steps, 1):
        print(f"  {i}. {step}")
    
    print(f"\n目标描述: {plan.target_description}")
    print(f"成功标准: {plan.success_criteria}")
    print(f"\n潜在挑战:")
    for i, challenge in enumerate(plan.potential_challenges, 1):
        print(f"  {i}. {challenge}")

# 运行
asyncio.run(plan_task())
```

### 自定义配置

```python
# 使用自定义配置
planner = TaskPlanner(
    api_key="your-api-key",
    api_base="https://api.example.com/v1",
    model="gpt-4-vision"
)

# 生成计划
plan = await planner.plan(
    start_url="https://example.com/articles",
    task="提取所有文章的标题和作者",
    target_text="标题"
)
```

### 处理复杂任务

```python
# 处理复杂的多步骤任务
plan = await planner.plan(
    start_url="https://example.com/forum",
    task="收集论坛中所有热门帖子的标题、作者和回复数",
    target_text="热门帖子"
)

print(f"任务分析: {plan.task_analysis}")
print(f"执行步骤数: {len(plan.steps)}")
print(f"潜在挑战数: {len(plan.potential_challenges)}")
```

---

## 📝 最佳实践

### 任务描述

1. **清晰具体**：任务描述应该清晰、具体、可执行
2. **包含目标**：明确说明要提取的目标信息
3. **提供上下文**：提供足够的上下文信息帮助 LLM 理解

### 计划生成

1. **使用规划器**：在执行复杂任务前使用规划器生成计划
2. **分析计划**：仔细分析生成的执行计划
3. **调整计划**：根据实际情况调整执行计划

### 配置管理

1. **使用专用配置**：为规划器使用专用的 API Key 和模型
2. **合理设置参数**：根据任务复杂度设置 temperature 和 max_tokens
3. **监控性能**：监控规划器的性能和成本

### 错误处理

1. **容错机制**：利用默认计划作为容错
2. **重试机制**：在解析失败时实现重试机制
3. **日志记录**：详细记录规划过程便于调试

---

## 🔍 故障排除

### 常见问题

1. **计划生成失败**
   - 检查 API Key 是否正确
   - 验证 API Base URL 是否可访问
   - 确认模型名称是否正确

2. **响应解析失败**
   - 检查 LLM 响应格式是否正确
   - 验证 JSON 解析逻辑是否正确
   - 确认容错机制是否生效

3. **计划质量不佳**
   - 检查任务描述是否清晰
   - 验证目标文本是否准确
   - 确认是否提供了足够的上下文

4. **性能问题**
   - 检查模型选择是否合适
   - 验证 max_tokens 设置是否合理
   - 确认是否使用了缓存

### 调试技巧

```python
# 检查规划器配置
print(f"API Key: {planner.api_key[:10]}...")
print(f"API Base: {planner.api_base}")
print(f"Model: {planner.model}")

# 检查生成的计划
print(f"任务分析: {plan.task_analysis}")
print(f"执行步骤数: {len(plan.steps)}")
print(f"目标描述: {plan.target_description}")
print(f"成功标准: {plan.success_criteria}")
print(f"潜在挑战数: {len(plan.potential_challenges)}")

# 检查 LLM 响应
print(f"LLM 响应: {response_text[:500]}...")
```

---

## 📚 方法参考

### TaskPlan 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `task_analysis` | str | 任务分析 |
| `steps` | list[str] | 执行步骤列表 |
| `target_description` | str | 目标描述 |
| `success_criteria` | str | 成功标准 |
| `potential_challenges` | list[str] | 潜在挑战 |

### TaskPlanner 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `plan()` | start_url, task, target_text | TaskPlan | 分析任务并生成执行计划 |

### 初始化参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `api_key` | str | 从配置读取 | API Key |
| `api_base` | str | 从配置读取 | API Base URL |
| `model` | str | 从配置读取 | 模型名称 |

---

## 📄 Prompt 模板

### planner.yaml

```yaml
system_prompt: |
  你是一个任务规划专家，擅长分析复杂的网页自动化任务并生成详细的执行计划。

  请根据用户提供的信息，生成一个清晰、可执行的执行计划。

user_prompt: |
  ## 任务信息
  
  - 起始 URL: {{start_url}}
  - 任务描述: {{task}}
  - 目标文本: {{target_text}}
  
  请分析这个任务并生成执行计划。
```

---

*最后更新: 2026-01-08*
