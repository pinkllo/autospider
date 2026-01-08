# browser_manager/engine.py - 浏览器引擎

browser_manager/engine.py 模块提供异步浏览器引擎，管理全局唯一的 Browser 实例。

---

## 📁 文件路径

```
common/browser_manager/engine.py
```

---

## 📑 函数目录

### 🚀 核心类
- `BrowserEngine` - 异步浏览器引擎

### 🔧 主要方法
- `start()` - 启动浏览器
- `stop()` - 停止浏览器
- `new_page()` - 创建新页面

---

## 🚀 核心功能

### BrowserEngine

异步浏览器引擎，管理全局唯一的 Browser 实例。

```python
from common.browser_manager.engine import BrowserEngine

# 创建浏览器引擎
engine = BrowserEngine(
    default_headless=True,
    default_viewport={"width": 1920, "height": 1080},
    default_browser_type="chromium"
)

# 启动浏览器
await engine.start()

# 创建新页面
page = await engine.new_page()

# 使用页面
await page.goto("https://example.com")

# 停止浏览器
await engine.stop()
```

---

## 💡 特性说明

### 资源复用

管理全局唯一的 Browser 实例，实现资源复用。

### 反检测

集成 playwright-stealth 反检测。

---

## 🔧 使用示例

### 基本使用

```python
import asyncio
from common.browser_manager.engine import BrowserEngine

async def browse():
    # 创建浏览器引擎
    engine = BrowserEngine(
        default_headless=True,
        default_viewport={"width": 1920, "height": 1080}
    )

    # 启动浏览器
    await engine.start()

    # 创建新页面
    page = await engine.new_page()

    # 使用页面
    await page.goto("https://example.com")
    title = await page.title()
    print(f"页面标题: {title}")

    # 停止浏览器
    await engine.stop()

# 运行
asyncio.run(browse())
```

---

## 📚 方法参考

### BrowserEngine 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `start()` | 无 | None | 启动浏览器 |
| `stop()` | 无 | None | 停止浏览器 |
| `new_page()` | 无 | Page | 创建新页面 |

---

*最后更新: 2026-01-08*
