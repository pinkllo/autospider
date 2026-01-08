# agent.py - LangGraph Agent

agent.py 模块提供 LangGraph Agent 图定义，实现纯视觉 SoM 浏览器 Agent。

---

## 📁 文件路径

```
src/autospider/extractor/graph/agent.py
```

---

## 📑 函数目录

### 🚀 核心类
- `GraphState` - LangGraph 状态定义
- `SoMAgent` - SoM 纯视觉 Agent

### 🔧 主要方法
- `run()` - 运行 Agent 并返回 XPath 脚本

### 🔍 内部方法
- `_observe()` - 观察节点：注入 SoM + 截图
- `_decide()` - 决策节点：调用 LLM
- `_act()` - 执行节点：执行动作
- `_check_done()` - 检查是否完成
- `_generate_script()` - 生成最终的 XPath 脚本

---

## 🚀 核心功能

### SoMAgent

SoM 纯视觉 Agent，使用 LangGraph 实现自动化任务。

```python
from autospider.extractor.graph.agent import SoMAgent, run_agent
from autospider.common.types import RunInput

# 创建运行输入
run_input = RunInput(
    start_url="https://example.com",
    task="收集商品价格信息",
    target_text="价格",
    max_steps=20,
    output_dir="output"
)

# 运行 Agent
script = await run_agent(page, run_input)

print(f"任务: {script.task}")
print(f"步骤数: {len(script.steps)}")
print(f"提取结果: {script.extracted_result}")
```

### Agent 流程

Agent 实现完整的自动化流程：

**0. 任务规划**
```python
# 分析任务并生成执行计划
plan = await planner.plan(
    start_url,
    task,
    target_text
)
```

**1. 导航到起始页面**
```python
await page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
```

**2. Observe: 注入 SoM 并截图**
```python
# 注入 SoM 并扫描
snapshot = await inject_and_scan(page)

# 截图（包含 SoM 标注）
screenshot_bytes, screenshot_base64 = await capture_screenshot_with_marks(page)
```

**3. Decide: 调用 LLM 决策**
```python
# 调用 LLM 决策
action = await decider.decide(
    agent_state,
    screenshot_base64,
    marks_text,
    target_found_in_page,
    scroll_info
)
```

**4. Act: 执行动作**
```python
# 执行动作
result, script_step = await executor.execute(
    action,
    mark_id_to_xpath,
    step_index
)
```

**5. Check: 检查是否完成**
```python
# 检查是否完成
if state["extracted_text"]:
    if target_text in state["extracted_text"]:
        state["done"] = True
        state["success"] = True
```

---

## 💡 特性说明

### LangGraph 状态管理

使用 TypedDict 定义 LangGraph 状态：

```python
class GraphState(TypedDict):
    """LangGraph 状态（简化版，用于图传递）"""
    
    # 输入
    start_url: str
    task: str
    target_text: str
    max_steps: int
    output_dir: str
    
    # 运行时状态
    step_index: int
    page_url: str
    page_title: str
    
    # 观察结果
    screenshot_base64: str
    marks_text: str
    mark_id_to_xpath: dict[int, list[str]]
    scroll_info: dict | None
    
    # 动作
    current_action: dict | None
    action_result: dict | None
    
    # 脚本沉淀
    script_steps: list[dict]
    
    # 状态标志
    done: bool
    success: bool
    error: str | None
    fail_count: int
    extracted_text: str | None
```

### 目标文本检测

自动检测页面中是否存在目标文本：

```python
# 检查页面中是否存在目标文本（精确匹配）
page_text = await page.evaluate("document.body.innerText")

if target_text in page_text:
    target_found_in_page = True
    print(f"✓ 页面中发现目标文本「{target_text}」")
    
    # 尝试定位包含目标文本的元素
    locator = page.locator(f"text={target_text}").first
    if await locator.count() > 0:
        bbox = await locator.bounding_box()
        text = await locator.inner_text()
        target_element_info = {
            "text": text[:200] if text else "",
            "bbox": bbox,
        }
```

### 脚本沉淀

自动沉淀可复用的 XPath 脚本步骤：

```python
# 记录脚本步骤
if script_step:
    script_step.screenshot_context = f"step_{step_index:03d}.png"
    state["script_steps"].append(script_step.model_dump())

# 生成最终脚本
script = XPathScript(
    task=state["task"],
    start_url=state["start_url"],
    target_text=state["target_text"],
    steps=[ScriptStep(**s) for s in state["script_steps"]],
    extracted_result=state["extracted_text"],
    created_at=datetime.now().isoformat(),
)
```

---

## 🔧 使用示例

### 基本使用

```python
import asyncio
from playwright.async_api import async_playwright
from autospider.extractor.graph.agent import run_agent
from autospider.common.types import RunInput

async def run_task():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # 创建运行输入
        run_input = RunInput(
            start_url="https://example.com/products",
            task="收集所有商品的价格信息",
            target_text="价格",
            max_steps=20,
            output_dir="output"
        )

        # 运行 Agent
        script = await run_agent(page, run_input)

        print(f"任务: {script.task}")
        print(f"步骤数: {len(script.steps)}")
        print(f"提取结果: {script.extracted_result}")

        await browser.close()

# 运行
asyncio.run(run_task())
```

### 自定义最大步骤数

```python
# 自定义最大步骤数
run_input = RunInput(
    start_url="https://example.com",
    task="提取文章标题",
    target_text="标题",
    max_steps=50,  # 最多 50 步
    output_dir="output"
)

script = await run_agent(page, run_input)
```

### 查看脚本步骤

```python
# 查看生成的脚本步骤
for i, step in enumerate(script.steps, 1):
    print(f"步骤 {i}:")
    print(f"  动作: {step.action}")
    print(f"  目标 XPath: {step.target_xpath}")
    print(f"  思考: {step.thinking}")
    print(f"  截图: {step.screenshot_context}")
```

---

## 📝 最佳实践

### 任务设计

1. **清晰的任务描述**：提供清晰、具体的任务描述
2. **准确的目标文本**：提供准确的目标文本用于匹配
3. **合理的步骤限制**：设置合理的最大步骤数

### Agent 配置

1. **选择合适的模型**：根据任务复杂度选择合适的模型
2. **设置合理的参数**：根据实际需求设置 temperature 和 max_tokens
3. **监控执行过程**：监控 Agent 执行过程便于调试

### 脚本使用

1. **验证脚本准确性**：验证生成的脚本是否准确
2. **测试脚本执行**：测试脚本是否可以正常执行
3. **优化脚本性能**：优化脚本性能提高执行效率

---

## 🔍 故障排除

### 常见问题

1. **Agent 执行失败**
   - 检查任务描述是否清晰
   - 验证目标文本是否准确
   - 确认页面加载完成

2. **脚本生成失败**
   - 检查动作执行是否成功
   - 验证脚本步骤是否完整
   - 确认截图是否保存成功

3. **目标文本未找到**
   - 检查目标文本是否正确
   - 验证页面是否包含目标文本
   - 确认文本匹配逻辑是否正确

### 调试技巧

```python
# 检查 Agent 状态
print(f"当前步骤: {state['step_index']}")
print(f"当前 URL: {state['page_url']}")
print(f"当前标题: {state['page_title']}")
print(f"是否完成: {state['done']}")
print(f"是否成功: {state['success']}")
print(f"失败次数: {state['fail_count']}")
print(f"提取文本: {state['extracted_text']}")

# 检查脚本步骤
print(f"脚本步骤数: {len(state['script_steps'])}")
for i, step in enumerate(state['script_steps'], 1):
    print(f"步骤 {i}: {step}")

# 检查截图文件
import os
screenshot_files = os.listdir(screenshots_dir)
print(f"截图文件数: {len(screenshot_files)}")
```

---

## 📚 方法参考

### SoMAgent 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `run()` | 无 | XPathScript | 运行 Agent 并返回 XPath 脚本 |
| `_observe()` | state | GraphState | 观察节点：注入 SoM + 截图 |
| `_decide()` | state | GraphState | 决策节点：调用 LLM |
| `_act()` | state | GraphState | 执行节点：执行动作 |
| `_check_done()` | state | GraphState | 检查是否完成 |
| `_generate_script()` | state | XPathScript | 生成最终的 XPath 脚本 |

### 便捷函数

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `run_agent()` | page, run_input | XPathScript | 运行 Agent 的便捷函数 |

---

## 📄 脚本格式

### XPathScript

```python
{
    "task": "收集商品价格信息",
    "start_url": "https://example.com/products",
    "target_text": "价格",
    "steps": [
        {
            "step": 1,
            "action": "click",
            "target_xpath": "//a[@class='product-link']",
            "xpath_alternatives": ["//div[@class='product']//a"],
            "thinking": "点击商品链接进入详情页",
            "screenshot_context": "step_001.png"
        },
        {
            "step": 2,
            "action": "extract",
            "target_xpath": "//span[@class='price']",
            "xpath_alternatives": ["//div[@class='price']"],
            "thinking": "提取价格信息",
            "screenshot_context": "step_002.png"
        }
    ],
    "extracted_result": "¥99.00",
    "created_at": "2026-01-08T10:00:00"
}
```

---

*最后更新: 2026-01-08*
