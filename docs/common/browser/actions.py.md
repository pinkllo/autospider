# actions.py - 动作执行器

actions.py 模块提供动作执行功能，负责执行 LLM 输出的各种浏览器操作，包括点击、输入、滚动等。

---

## 📁 文件路径

```
src/autospider/common/browser/actions.py
```

---

## 📑 函数目录

### 🎯 动作执行器
- `ActionExecutor` - 动作执行器主类
- `execute(action, mark_id_to_xpath, step_index)` - 执行单个动作

### 🔧 内部方法
- `_find_element_by_xpath_list(xpaths)` - 按优先级查找元素
- `_execute_click(action, mark_id_to_xpath, step_index)` - 执行点击动作
- `_execute_type(action, mark_id_to_xpath, step_index)` - 执行输入动作
- `_execute_press(action, mark_id_to_xpath, step_index)` - 执行按键动作
- `_execute_scroll(action, step_index)` - 执行滚动动作
- `_execute_navigate(action, step_index)` - 执行导航动作
- `_execute_wait(action, step_index)` - 执行等待动作
- `_execute_extract(action, mark_id_to_xpath, step_index)` - 执行提取动作
- `_execute_go_back(action, step_index)` - 执行返回上一页动作

---

## 🚀 核心功能

### ActionExecutor

动作执行器主类，负责执行各种浏览器操作并沉淀为可复用的 XPath 脚本步骤。

```python
from autospider.common.browser.actions import ActionExecutor

# 创建动作执行器
executor = ActionExecutor(page)

# 执行动作
from autospider.common.types import Action, ActionType

action = Action(
    action=ActionType.CLICK,
    mark_id=5,
    target_text="登录按钮",
    thinking="点击登录按钮提交表单"
)

result, script_step = await executor.execute(
    action,
    mark_id_to_xpath={5: ["//button[@id='login']", "//button[text()='登录']"]},
    step_index=1
)

print(f"执行成功: {result.success}")
if script_step:
    print(f"生成的脚本步骤: {script_step.model_dump_json()}")
```

### Priority Fallback 策略

按优先级尝试多个 XPath，返回第一个匹配的元素。

```python
# 按优先级尝试多个 XPath
xpaths = [
    "//button[@id='login']",           # 优先级 1：最稳定
    "//button[@data-testid='login']",   # 优先级 2：testid
    "//button[@aria-label='登录']",     # 优先级 3：aria
    "//button[text()='登录']",          # 优先级 4：文本
    "//div[@class='btn']/button"        # 优先级 5：相对路径
]

# 执行器会依次尝试这些 XPath，直到找到可用的元素
```

---

## 💡 特性说明

### 支持的动作类型

ActionExecutor 支持多种动作类型：

| ActionType | 说明 | 关键参数 |
|------------|------|----------|
| `CLICK` | 点击元素 | `mark_id` |
| `TYPE` | 输入文本 | `mark_id`, `text` |
| `PRESS` | 按键 | `key`, `mark_id`（可选） |
| `SCROLL` | 滚动 | `scroll_delta` |
| `NAVIGATE` | 导航 | `url` |
| `WAIT` | 等待 | `timeout_ms` |
| `EXTRACT` | 提取文本 | `mark_id`, `target_text` |
| `GO_BACK` | 返回上一页 | 无 |
| `DONE` | 完成任务 | 无 |
| `RETRY` | 重试当前步骤 | 无 |

### 智能提取功能

EXTRACT 动作支持智能提取，特别是对表格数据的处理：

```python
# 如果提取的是表头（th），自动获取同行数据（td）
extract_action = Action(
    action=ActionType.EXTRACT,
    mark_id=5,  # 指向 th 元素
    target_text="价格"
)

result, script_step = await executor.execute(
    extract_action,
    mark_id_to_xpath={5: ["//table//th[contains(text(),'价格')]"]},
    step_index=1
)

# 提取结果会自动获取同行 td 的内容
print(f"提取的文本: {result.extracted_text}")
```

### 新标签页检测

CLICK 动作自动检测新标签页的打开：

```python
# 点击会自动检测是否打开了新标签页
click_action = Action(
    action=ActionType.CLICK,
    mark_id=5,
    target_text="在新标签页打开"
)

result, script_step = await executor.execute(
    click_action,
    mark_id_to_xpath={5: ["//a[@target='_blank']"]},
    step_index=1
)

# 如果检测到新标签页，会自动切换到新标签页
```

---

## 🔧 使用示例

### 完整的登录流程

```python
import asyncio
from autospider.common.browser.actions import ActionExecutor
from autospider.common.types import Action, ActionType

async def login_flow(username, password):
    """完整的登录流程示例"""

    # 创建动作执行器
    executor = ActionExecutor(page)

    # 输入用户名
    type_action = Action(
        action=ActionType.TYPE,
        mark_id=1,
        text=username,
        target_text="用户名输入框",
        thinking="在用户名输入框中输入用户名"
    )
    result, _ = await executor.execute(type_action, {}, 1)

    # 输入密码
    type_action = Action(
        action=ActionType.TYPE,
        mark_id=2,
        text=password,
        target_text="密码输入框",
        thinking="在密码输入框中输入密码"
    )
    result, _ = await executor.execute(type_action, {}, 2)

    # 点击登录按钮
    click_action = Action(
        action=ActionType.CLICK,
        mark_id=3,
        target_text="登录按钮",
        thinking="点击登录按钮提交表单"
    )
    result, _ = await executor.execute(
        click_action,
        {3: ["//button[@type='submit']", "//button[text()='登录']"]},
        3
    )

    print("登录流程完成")

# 使用示例
asyncio.run(login_flow("testuser", "testpass"))
```

### 数据提取流程

```python
import asyncio
from autospider.common.browser.actions import ActionExecutor
from autospider.common.types import Action, ActionType

async def extract_data():
    """数据提取流程示例"""

    # 创建动作执行器
    executor = ActionExecutor(page)

    # 导航到目标页面
    navigate_action = Action(
        action=ActionType.NAVIGATE,
        url="https://example.com/product/123",
        thinking="导航到商品详情页"
    )
    result, _ = await executor.execute(navigate_action, {}, 1)

    # 提取商品名称
    extract_action = Action(
        action=ActionType.EXTRACT,
        mark_id=1,
        target_text="商品名称",
        thinking="提取商品名称"
    )
    result, _ = await executor.execute(
        extract_action,
        {1: ["//h1[@class='product-title']"]},
        2
    )
    product_name = result.extracted_text

    # 提取价格
    extract_action = Action(
        action=ActionType.EXTRACT,
        mark_id=2,
        target_text="价格",
        thinking="提取商品价格"
    )
    result, _ = await executor.execute(
        extract_action,
        {2: ["//span[@class='price']"]},
        3
    )
    price = result.extracted_text

    print(f"商品名称: {product_name}")
    print(f"价格: {price}")

    return {
        "name": product_name,
        "price": price
    }

# 使用示例
data = asyncio.run(extract_data())
```

---

## 📝 最佳实践

### 动作设计

1. **原子性**：每个动作应该完成一个独立的操作
2. **可重试性**：动作应该支持失败重试
3. **描述性**：为每个动作提供清晰的描述
4. **超时设置**：为每个动作设置合理的超时时间

### XPath 优先级

1. **最稳定优先**：使用最稳定的 XPath 作为第一优先级
2. **备选方案**：提供多个备选 XPath
3. **降级策略**：实现 Priority Fallback 策略
4. **唯一性检查**：确保 XPath 唯一性

### 错误处理

1. **动作验证**：执行前验证动作参数有效性
2. **异常捕获**：捕获并处理各种异常情况
3. **状态恢复**：异常后能够恢复浏览器状态
4. **日志记录**：详细记录操作日志

---

## 🔍 故障排除

### 常见问题

1. **动作执行失败**
   - 检查 mark_id 是否正确
   - 验证 XPath 候选是否有效
   - 确认元素是否可见和可交互

2. **XPath 定位失败**
   - 检查 XPath 语法是否正确
   - 验证元素是否在 iframe 中
   - 确认页面加载状态

3. **新标签页处理异常**
   - 检查浏览器标签页管理
   - 验证页面切换逻辑
   - 确认超时设置是否合理

### 调试技巧

```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 检查动作执行结果
print(f"执行成功: {result.success}")
print(f"错误信息: {result.error}")
print(f"新 URL: {result.new_url}")
print(f"提取的文本: {result.extracted_text}")

# 检查脚本步骤
if script_step:
    print(f"步骤序号: {script_step.step}")
    print(f"动作类型: {script_step.action}")
    print(f"目标 XPath: {script_step.target_xpath}")
    print(f"备选 XPath: {script_step.xpath_alternatives}")
```

---

## 📚 方法参考

### ActionExecutor 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `execute(action, mark_id_to_xpath, step_index)` | action: Action, mark_id_to_xpath: dict, step_index: int | tuple[ActionResult, ScriptStep \| None] | 执行单个动作 |
| `_find_element_by_xpath_list(xpaths)` | xpaths: list[str] | tuple[Locator \| None, str \| None] | 按优先级查找元素 |
| `_execute_click(action, mark_id_to_xpath, step_index)` | action: Action, mark_id_to_xpath: dict, step_index: int | tuple[ActionResult, ScriptStep \| None] | 执行点击动作 |
| `_execute_type(action, mark_id_to_xpath, step_index)` | action: Action, mark_id_to_xpath: dict, step_index: int | tuple[ActionResult, ScriptStep \| None] | 执行输入动作 |
| `_execute_press(action, mark_id_to_xpath, step_index)` | action: Action, mark_id_to_xpath: dict, step_index: int | tuple[ActionResult, ScriptStep \| None] | 执行按键动作 |
| `_execute_scroll(action, step_index)` | action: Action, step_index: int | tuple[ActionResult, ScriptStep \| None] | 执行滚动动作 |
| `_execute_navigate(action, step_index)` | action: Action, step_index: int | tuple[ActionResult, ScriptStep \| None] | 执行导航动作 |
| `_execute_wait(action, step_index)` | action: Action, step_index: int | tuple[ActionResult, ScriptStep \| None] | 执行等待动作 |
| `_execute_extract(action, mark_id_to_xpath, step_index)` | action: Action, mark_id_to_xpath: dict, step_index: int | tuple[ActionResult, ScriptStep \| None] | 执行提取动作 |
| `_execute_go_back(action, step_index)` | action: Action, step_index: int | tuple[ActionResult, ScriptStep \| None] | 执行返回上一页动作 |

---

*最后更新: 2026-01-08*
