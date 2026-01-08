# browser_manager/interaction.py - 人工交互工具

browser_manager/interaction.py 模块提供自动化流程中人工介入的辅助功能。

---

## 📁 文件路径

```
common/browser_manager/interaction.py
```

---

## 📑 函数目录

### 🚀 核心函数
- `handle_human_login()` - 处理人工登录

---

## 🚀 核心功能

### handle_human_login

处理人工登录，等待用户完成登录操作。

```python
from common.browser_manager.interaction import handle_human_login

# 处理人工登录
page = await handle_human_login(
    page=page,
    auth_file="auth.json",
    success_selector="//button[contains(text(),'登录成功')]",
    target_url_contains="dashboard",
    wait_url_change=True,
    timeout=300000
)

print(f"登录成功: {page.url}")
```

---

## 💡 特性说明

### 浏览器内提示

在浏览器内显示提示 UI，引导用户操作。

### 多种检测方式

支持多种检测方式判断登录是否成功。

---

## 🔧 使用示例

### 基本使用

```python
import asyncio
from playwright.async_api import async_playwright
from common.browser_manager.interaction import handle_human_login

async def login():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        await page.goto("https://example.com/login")

        # 处理人工登录
        page = await handle_human_login(
            page=page,
            auth_file="auth.json",
            success_selector="//button[contains(text(),'登录成功')]",
            target_url_contains="dashboard",
            timeout=300000
        )

        print(f"登录成功: {page.url}")

        await browser.close()

# 运行
asyncio.run(login())
```

---

## 📚 函数参考

### 函数列表

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `handle_human_login()` | page, auth_file, success_selector, target_url_contains, wait_url_change, timeout | Page | 处理人工登录 |

---

*最后更新: 2026-01-08*
