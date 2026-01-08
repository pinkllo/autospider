# session.py - 浏览器会话管理

session.py 模块提供浏览器会话管理功能，负责创建和管理 Playwright 页面实例。

---

## 📁 文件路径

```
src/autospider/common/browser/session.py
```

---

## 📑 函数目录

### 🚀 核心函数
- `create_browser_session()` - 创建浏览器会话
- `close_browser_session()` - 关闭浏览器会话

---

## 🚀 核心功能

### 创建浏览器会话

创建 Playwright 浏览器和页面实例。

```python
from autospider.common.browser.session import create_browser_session

# 创建浏览器会话
browser, context, page = await create_browser_session(
    headless=True,
    viewport_width=1280,
    viewport_height=720
)

# 使用页面
await page.goto("https://example.com")

# 关闭会话
await close_browser_session(browser, context)
```

---

## 💡 特性说明

### Playwright 集成

使用 Playwright 提供浏览器自动化功能。

### 配置管理

支持通过配置文件管理浏览器参数。

---

## 🔧 使用示例

### 基本使用

```python
import asyncio
from autospider.common.browser.session import create_browser_session, close_browser_session

async def browse():
    # 创建浏览器会话
    browser, context, page = await create_browser_session(
        headless=True,
        viewport_width=1280,
        viewport_height=720
    )

    # 使用页面
    await page.goto("https://example.com")
    title = await page.title()
    print(f"页面标题: {title}")

    # 关闭会话
    await close_browser_session(browser, context)

# 运行
asyncio.run(browse())
```

---

## 📚 函数参考

### 函数列表

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `create_browser_session()` | headless, viewport_width, viewport_height | tuple | 创建浏览器会话 |
| `close_browser_session()` | browser, context | None | 关闭浏览器会话 |

---

*最后更新: 2026-01-08*
