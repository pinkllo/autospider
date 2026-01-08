# types.py - 核心数据类型定义

types.py 模块定义 AutoSpider 项目使用的核心数据类型，包括 SoM 标注、动作定义、XPath 脚本和 LangGraph 状态等。

---

## 📁 文件路径

```
src/autospider/common/types.py
```

---

## 📑 函数目录

### 📦 输入参数
- `RunInput` - Agent 运行输入参数

### 🎯 SoM 标注相关
- `BoundingBox` - 元素边界框
- `XPathCandidate` - XPath 候选项
- `ElementMark` - SoM 标注的元素
- `ScrollInfo` - 页面滚动状态
- `SoMSnapshot` - SoM 快照

### 🎬 动作定义
- `ActionType` - 动作类型枚举
- `Action` - LLM 输出的动作
- `ActionResult` - 动作执行结果

### 📜 XPath 脚本
- `ScriptStepType` - 脚本步骤类型
- `ScriptStep` - XPath 脚本步骤
- `XPathScript` - 完整的 XPath 脚本

### 🔄 LangGraph 状态
- `AgentState` - Agent 状态

---

## 🚀 核心功能

### RunInput

Agent 运行输入参数，定义了启动 Agent 所需的所有参数。

```python
from autospider.common.types import RunInput

input_data = RunInput(
    start_url="https://example.com",
    task="点击登录按钮，输入用户名和密码",
    target_text="欢迎回来",
    max_steps=30,
    headless=True,
    output_dir="output"
)

print(f"起始 URL: {input_data.start_url}")
print(f"任务描述: {input_data.task}")
```

### BoundingBox

元素边界框，使用视口坐标表示元素的位置和大小。

```python
from autospider.common.types import BoundingBox

bbox = BoundingBox(
    x=100.5,
    y=200.3,
    width=300.0,
    height=50.0
)

# 获取中心坐标
center = bbox.center
print(f"中心坐标: {center}")
```

### ElementMark

SoM 标注的元素，包含元素的完整信息和 XPath 候选项。

```python
from autospider.common.types import ElementMark, BoundingBox, XPathCandidate

mark = ElementMark(
    mark_id=5,
    tag="button",
    role="button",
    text="登录",
    aria_label="登录按钮",
    placeholder=None,
    href=None,
    input_type=None,
    bbox=BoundingBox(x=100, y=200, width=300, height=50),
    center_normalized=(0.5, 0.5),
    xpath_candidates=[
        XPathCandidate(
            xpath="//button[@id='login']",
            priority=1,
            strategy="id",
            confidence=1.0
        )
    ],
    is_visible=True,
    z_index=0
)

print(f"元素标记: {mark.mark_id}")
print(f"元素标签: {mark.tag}")
print(f"元素文本: {mark.text}")
```

### Action

LLM 输出的动作，定义了 Agent 可以执行的所有操作类型。

```python
from autospider.common.types import Action, ActionType

action = Action(
    action=ActionType.CLICK,
    mark_id=5,
    target_text="登录按钮",
    text=None,
    key=None,
    url=None,
    scroll_delta=None,
    timeout_ms=5000,
    thinking="需要点击登录按钮来提交表单",
    expectation="页面跳转到首页"
)

print(f"动作类型: {action.action}")
print(f"目标元素: {action.mark_id}")
print(f"思考过程: {action.thinking}")
```

### ScriptStep

XPath 脚本步骤，可复用的自动化操作步骤。

```python
from autospider.common.types import ScriptStep, ScriptStepType

step = ScriptStep(
    step=1,
    action=ScriptStepType.CLICK,
    target_xpath="//button[@id='login']",
    xpath_alternatives=[
        "//button[@data-testid='login']",
        "//button[@aria-label='登录']",
        "//button[text()='登录']"
    ],
    value=None,
    key=None,
    url=None,
    scroll_delta=None,
    wait_condition="networkidle",
    timeout_ms=5000,
    description="点击登录按钮",
    screenshot_context=None
)

print(f"步骤序号: {step.step}")
print(f"动作类型: {step.action}")
print(f"目标 XPath: {step.target_xpath}")
```

### AgentState

LangGraph Agent 状态，包含 Agent 运行时的所有状态信息。

```python
from autospider.common.types import AgentState, RunInput

state = AgentState(
    input=RunInput(
        start_url="https://example.com",
        task="点击登录按钮",
        target_text="欢迎回来"
    ),
    step_index=0,
    page_url="https://example.com",
    page_title="示例网站",
    current_snapshot=None,
    mark_id_to_xpath={},
    last_action=None,
    last_result=None,
    action_history=[],
    script_steps=[],
    done=False,
    success=False,
    error=None,
    fail_count=0,
    max_fail_count=3
)

print(f"当前步骤: {state.step_index}")
print(f"页面 URL: {state.page_url}")
print(f"是否完成: {state.done}")
```

---

## 💡 特性说明

### 类型注解

所有数据类型都使用 Pydantic 的 BaseModel，提供类型验证和序列化功能：

```python
from pydantic import BaseModel, Field

class ExampleModel(BaseModel):
    name: str = Field(..., description="名称")
    age: int = Field(default=0, description="年龄")

# 类型验证
try:
    model = ExampleModel(name="Alice", age="invalid")
except ValidationError as e:
    print(f"验证失败: {e}")
```

### 枚举类型

使用枚举类型限制可用的动作类型：

```python
from autospider.common.types import ActionType

# 所有可用的动作类型
print(f"可用的动作类型:")
for action_type in ActionType:
    print(f"  - {action_type.value}")

# 动作类型包括:
# - CLICK: 点击元素
# - TYPE: 输入文本
# - PRESS: 按键
# - SCROLL: 滚动页面
# - NAVIGATE: 导航到 URL
# - WAIT: 等待
# - EXTRACT: 提取文本
# - GO_BACK: 返回上一页
# - DONE: 完成任务
# - RETRY: 重试当前步骤
```

### 默认值

所有可选字段都有合理的默认值：

```python
from autospider.common.types import RunInput

# 使用默认值
input_data = RunInput(
    start_url="https://example.com",
    task="点击登录按钮",
    target_text="欢迎回来"
)

# max_steps 将使用默认值 20
# headless 将使用默认值 False
# output_dir 将使用默认值 "output"
```

---

## 🔧 使用示例

### 完整的类型使用流程

```python
from autospider.common.types import (
    RunInput,
    Action,
    ActionType,
    ActionResult,
    ScriptStep,
    ScriptStepType,
    AgentState
)

# 创建输入参数
input_data = RunInput(
    start_url="https://example.com/login",
    task="点击登录按钮，输入用户名和密码",
    target_text="欢迎回来",
    max_steps=10
)

# 创建动作
action = Action(
    action=ActionType.CLICK,
    mark_id=5,
    target_text="登录按钮",
    thinking="点击登录按钮提交表单"
)

# 创建执行结果
result = ActionResult(
    success=True,
    error=None,
    new_url="https://example.com/home",
    extracted_text=None,
    screenshot_path="screenshots/step1.png"
)

# 创建脚本步骤
step = ScriptStep(
    step=1,
    action=ScriptStepType.CLICK,
    target_xpath="//button[@id='login']",
    xpath_alternatives=[
        "//button[@data-testid='login']",
        "//button[@aria-label='登录']"
    ],
    description="点击登录按钮"
)

# 创建 Agent 状态
state = AgentState(
    input=input_data,
    step_index=1,
    page_url="https://example.com/login",
    page_title="登录页面",
    done=False,
    success=False
)

print(f"状态: 步骤 {state.step_index}/{input_data.max_steps}")
```

### 类型验证和序列化

```python
from autospider.common.types import Action, ActionType
import json

# 创建动作
action = Action(
    action=ActionType.CLICK,
    mark_id=5,
    thinking="点击登录按钮"
)

# 验证类型
try:
    # 尝试创建无效动作
    invalid_action = Action(
        action=ActionType.CLICK,
        mark_id=None,  # mark_id 是必需的
        thinking="点击登录按钮"
    )
except Exception as e:
    print(f"验证失败: {e}")

# 序列化为 JSON
action_json = action.model_dump_json(indent=2)
print(f"动作 JSON:\n{action_json}")

# 从 JSON 反序列化
action_dict = json.loads(action_json)
restored_action = Action(**action_dict)
print(f"恢复的动作: {restored_action.action}")
```

---

## 📝 最佳实践

### 类型定义

1. **类型注解**：始终使用类型注解
2. **默认值**：为可选字段提供合理的默认值
3. **验证逻辑**：使用 Pydantic 的验证器
4. **文档字符串**：为每个类型添加详细的文档

### 数据验证

1. **必填字段**：使用 `Field(...)` 标记必填字段
2. **可选字段**：使用 `Field(default=...)` 提供默认值
3. **枚举类型**：使用枚举限制可用值
4. **类型转换**：使用 Pydantic 的类型转换功能

### 序列化

1. **JSON 格式**：使用 `model_dump_json()` 序列化为 JSON
2. **字典格式**：使用 `model_dump()` 序列化为字典
3. **自定义编码**：使用 `json_serializer` 参数
4. **排除字段**：使用 `exclude` 参数

---

## 🔍 故障排除

### 常见问题

1. **类型验证失败**
   - 检查字段类型是否正确
   - 验证必填字段是否提供
   - 确认枚举值是否在有效范围内

2. **序列化失败**
   - 检查对象是否可序列化
   - 验证自定义类型是否实现了序列化方法
   - 确认循环引用是否正确处理

3. **反序列化失败**
   - 检查 JSON 格式是否正确
   - 验证字段名称是否匹配
   - 确认数据类型是否兼容

### 调试技巧

```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 检查类型定义
print(f"动作类型: {ActionType.__members__}")

# 验证数据
try:
    action = Action(
        action=ActionType.CLICK,
        mark_id=5,
        thinking="点击登录按钮"
    )
    print(f"动作验证成功: {action.action}")
except Exception as e:
    print(f"动作验证失败: {e}")

# 序列化检查
action_json = action.model_dump_json(indent=2)
print(f"序列化结果:\n{action_json}")
```

---

## 📚 类型参考

### RunInput 字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|--------|--------|------|
| start_url | str | 是 | - | 起始 URL |
| task | str | 是 | - | 任务描述（自然语言） |
| target_text | str | 是 | - | 提取目标文本 |
| max_steps | int | 否 | 20 | 最大执行步数 |
| headless | bool | 否 | False | 无头模式 |
| output_dir | str | 否 | "output" | 输出目录 |

### Action 字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|--------|--------|------|
| action | ActionType | 是 | - | 动作类型 |
| mark_id | int | 否 | None | 目标元素编号 |
| target_text | str | 否 | None | 目标文本（用于校验） |
| text | str | 否 | None | 输入文本（type 动作） |
| key | str | 否 | None | 按键（press 动作） |
| url | str | 否 | None | 导航 URL |
| scroll_delta | tuple[int, int] | 否 | None | 滚动量 (dx, dy) |
| timeout_ms | int | 否 | 5000 | 等待超时 |
| thinking | str | 否 | "" | LLM 决策推理过程 |
| expectation | str | 否 | None | 预期结果（用于校验） |

### ActionResult 字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|--------|--------|------|
| success | bool | 是 | - | 是否成功 |
| error | str | 否 | None | 错误信息 |
| new_url | str | 否 | None | 新 URL |
| extracted_text | str | 否 | None | 提取的文本 |
| screenshot_path | str | 否 | None | 截图路径 |

### ScriptStep 字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|--------|--------|------|
| step | int | 是 | - | 步骤序号 |
| action | ScriptStepType | 是 | - | 动作类型 |
| target_xpath | str | 否 | None | 目标元素 XPath |
| xpath_alternatives | list[str] | 否 | [] | 备选 XPath 列表 |
| value | str | 否 | None | 输入值（支持 ${VAR} 占位符） |
| key | str | 否 | None | 按键 |
| url | str | 否 | None | 导航 URL |
| scroll_delta | tuple[int, int] | 否 | None | 滚动量 |
| wait_condition | str | 否 | None | 等待条件 |
| timeout_ms | int | 否 | 5000 | 超时时间 |
| description | str | 否 | "" | 步骤描述 |
| screenshot_context | str | 否 | None | 截图路径（调试用） |

---

*最后更新: 2026-01-08*
