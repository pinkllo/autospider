# Browser 子模块

Browser 子模块提供浏览器操作的核心功能，包括动作执行器和浏览器会话管理。

---

## 📁 模块结构

```
src/autospider/common/browser/
├── __init__.py              # 模块导出
├── actions.py               # 动作执行器
└── session.py               # 浏览器会话管理
```

---

## 📑 函数目录

### 🎯 动作执行器 (actions.py)
- `ActionExecutor` - 动作执行器主类
- `execute(action, mark_id_to_xpath, step_index)` - 执行单个动作
- `_find_element_by_xpath_list(xpaths)` - 按优先级查找元素
- `_execute_click()` - 执行点击动作
- `_execute_type()` - 执行输入动作
- `_execute_press()` - 执行按键动作
- `_execute_scroll()` - 执行滚动动作
- `_execute_navigate()` - 执行导航动作
- `_execute_wait()` - 执行等待动作
- `_execute_extract()` - 执行提取动作
- `_execute_go_back()` - 执行返回上一页动作

### 💼 浏览器会话管理 (session.py)
- `BrowserSession` - 浏览器会话管理器
- `start()` - 启动浏览器并返回 Page
- `stop()` - 关闭浏览器
- `page` - 获取当前 Page
- `navigate(url, wait_until)` - 导航到指定 URL
- `wait_for_stable(timeout_ms)` - 等待页面稳定
- `create_browser_session()` - 创建浏览器会话上下文管理器

---

## 🚀 核心功能

### 动作执行器

ActionExecutor 类负责执行各种浏览器操作，支持点击、输入、滚动等常见动作。

```python
from autospider.common.browser.actions import ActionExecutor

# 创建动作执行器
executor = ActionExecutor(page)

# 定义动作
from autospider.common.types import Action, ActionType

click_action = Action(
    action=ActionType.CLICK,
    mark_id=5,
    target_text="登录按钮",
    thinking="需要点击登录按钮来提交表单"
)

# 执行动作
result, script_step = await executor.execute(
    click_action,
    mark_id_to_xpath={5: ["//button[@id='login']", "//button[text()='登录']"]},
    step_index=1
)

print(f"执行成功: {result.success}")
if script_step:
    print(f"生成的脚本步骤: {script_step.model_dump_json()}")
```

### 浏览器会话管理

BrowserSession 类管理浏览器的会话状态，包括Cookie、本地存储和会话数据。

```python
from autospider.common.browser.session import create_browser_session

# 使用上下文管理器（推荐）
async with create_browser_session(
    headless=True,
    viewport_width=1920,
    viewport_height=1080
) as session:
    page = session.page
    await session.navigate("https://example.com")
    await session.wait_for_stable()

    # 执行其他操作...
    title = await page.title()
    print(f"页面标题: {title}")
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

### Priority Fallback 策略

ActionExecutor 使用 Priority Fallback 策略来定位元素：

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
from autospider.common.browser.session import create_browser_session
from autospider.common.types import Action, ActionType

async def login_flow(username, password):
    """完整的登录流程示例"""

    async with create_browser_session(headless=False) as session:
        page = session.page
        executor = ActionExecutor(page)

        # 导航到登录页面
        await session.navigate("https://example.com/login")
        await session.wait_for_stable()

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

        # 等待登录完成
        await session.wait_for_stable()

        print("登录成功")

# 使用示例
asyncio.run(login_flow("testuser", "testpass"))
```

### 数据提取流程

```python
import asyncio
from autospider.common.browser.actions import ActionExecutor
from autospider.common.browser.session import create_browser_session
from autospider.common.types import Action, ActionType

async def extract_data():
    """数据提取流程示例"""

    async with create_browser_session(headless=True) as session:
        page = session.page
        executor = ActionExecutor(page)

        # 导航到目标页面
        await session.navigate("https://example.com/product/123")
        await session.wait_for_stable()

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
            1
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
            2
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

### 滚动加载更多

```python
import asyncio
from autospider.common.browser.actions import ActionExecutor
from autospider.common.browser.session import create_browser_session
from autospider.common.types import Action, ActionType

async def scroll_and_collect():
    """滚动加载更多内容示例"""

    async with create_browser_session(headless=True) as session:
        page = session.page
        executor = ActionExecutor(page)

        # 导航到列表页
        await session.navigate("https://example.com/products")
        await session.wait_for_stable()

        # 滚动加载更多
        for i in range(5):
            # 向下滚动
            scroll_action = Action(
                action=ActionType.SCROLL,
                scroll_delta=(0, 500),
                thinking=f"向下滚动加载更多内容（第{i+1}次）"
            )
            result, _ = await executor.execute(scroll_action, {}, i + 1)

            # 等待内容加载
            await asyncio.sleep(1)

            print(f"已滚动 {i+1} 次")

        print("滚动完成")

# 使用示例
asyncio.run(scroll_and_collect())
```

---

## 📝 最佳实践

### 动作设计

1. **原子性**：每个动作应该完成一个独立的操作
2. **可重试性**：动作应该支持失败重试
3. **描述性**：为每个动作提供清晰的描述
4. **超时设置**：合理设置动作超时时间

### 会话管理

1. **上下文管理器**：使用 `create_browser_session()` 确保资源正确释放
2. **异常处理**：使用 try-finally 块确保资源释放
3. **状态检查**：定期检查会话状态
4. **资源清理**：及时清理不再需要的资源

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

2. **会话管理异常**
   - 检查浏览器是否正确启动
   - 验证页面加载状态
   - 确认资源是否正确释放

3. **提取结果不准确**
   - 检查元素选择器是否正确
   - 验证页面加载状态
   - 确认元素是否在 iframe 中

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

# 检查会话状态
print(f"当前 URL: {page.url}")
print(f"页面标题: {await page.title()}")
```

---

*最后更新: 2026-01-08*
