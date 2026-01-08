# api.py - SoM (Set of Marks) API

api.py 模块提供 SoM (Set of Marks) API，负责页面元素标记和截图功能。

---

## 📁 文件路径

```
src/autospider/common/som/api.py
```

---

## 📑 函数目录

### 🚀 核心函数
- `inject_and_scan()` - 注入 SoM 并扫描页面
- `capture_screenshot_with_marks()` - 截取带 SoM 标注的截图
- `clear_overlay()` - 清除覆盖层
- `build_mark_id_to_xpath_map()` - 构建 mark_id 到 xpath 的映射
- `format_marks_for_llm()` - 格式化 marks 供 LLM 使用
- `set_overlay_visibility()` - 设置覆盖层可见性

---

## 🚀 核心功能

### inject_and_scan

注入 SoM 并扫描页面，返回元素快照。

```python
from autospider.common.som import inject_and_scan

# 注入 SoM 并扫描页面
snapshot = await inject_and_scan(page)

print(f"发现 {len(snapshot.marks)} 个可交互元素")
```

### capture_screenshot_with_marks

截取带 SoM 标注的截图。

```python
from autospider.common.som import capture_screenshot_with_marks

# 截取带 SoM 标注的截图
screenshot_bytes, screenshot_base64 = await capture_screenshot_with_marks(page)

# 保存截图
screenshot_path = Path("output/screenshot.png")
screenshot_path.write_bytes(screenshot_bytes)
```

### clear_overlay

清除覆盖层。

```python
from autospider.common.som import clear_overlay

# 清除覆盖层
await clear_overlay(page)
```

---

## 💡 特性说明

### SoM 标注

自动为页面元素添加数字标记，便于 LLM 理解。

### 多种选择器

支持多种选择器策略，提供多个 XPath 候选。

---

## 🔧 使用示例

### 基本使用

```python
import asyncio
from playwright.async_api import async_playwright
from autospider.common.som import (
    inject_and_scan,
    capture_screenshot_with_marks,
    clear_overlay
)

async def scan_page():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        await page.goto("https://example.com")

        # 注入 SoM 并扫描页面
        snapshot = await inject_and_scan(page)
        print(f"发现 {len(snapshot.marks)} 个可交互元素")

        # 截取带 SoM 标注的截图
        screenshot_bytes, screenshot_base64 = await capture_screenshot_with_marks(page)

        # 清除覆盖层
        await clear_overlay(page)

        await browser.close()

# 运行
asyncio.run(scan_page())
```

---

## 📚 函数参考

### 函数列表

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `inject_and_scan()` | page | SoMSnapshot | 注入 SoM 并扫描页面 |
| `capture_screenshot_with_marks()` | page | tuple[bytes, str] | 截取带 SoM 标注的截图 |
| `clear_overlay()` | page | None | 清除覆盖层 |
| `build_mark_id_to_xpath_map()` | snapshot | dict[int, list[str]] | 构建 mark_id 到 xpath 的映射 |
| `format_marks_for_llm()` | snapshot | str | 格式化 marks 供 LLM 使用 |
| `set_overlay_visibility()` | page, visible | None | 设置覆盖层可见性 |

---

*最后更新: 2026-01-08*
