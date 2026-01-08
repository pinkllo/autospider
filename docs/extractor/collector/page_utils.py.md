# page_utils.py - 页面操作工具

page_utils.py 模块提供页面操作工具函数，包括页面滚动检测和智能滚动。

---

## 📁 文件路径

```
src/autospider/extractor/collector/page_utils.py
```

---

## 📑 函数目录

### 🚀 核心函数
- `is_at_page_bottom(page, threshold=50)` - 检测页面是否已经滚动到底部
- `smart_scroll(page, distance=500)` - 智能滚动页面

---

## 🚀 核心功能

### is_at_page_bottom

检测页面是否已经滚动到底部。

```python
from autospider.extractor.collector.page_utils import is_at_page_bottom

# 检测页面是否到达底部
is_bottom = await is_at_page_bottom(page, threshold=50)

if is_bottom:
    print("已到达页面底部")
else:
    print("未到达页面底部")
```

### smart_scroll

智能滚动页面，如果已到达底部则不滚动。

```python
from autospider.extractor.collector.page_utils import smart_scroll

# 智能滚动 500 像素
success = await smart_scroll(page, distance=500)

if success:
    print("滚动成功")
else:
    print("已到达页面底部，无法继续滚动")
```

---

## 💡 特性说明

### 底部检测

使用 JavaScript 检测页面滚动位置：

```python
result = await page.evaluate("""
    () => {
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        const scrollHeight = document.documentElement.scrollHeight;
        const clientHeight = window.innerHeight;
        return {
            scrollTop: scrollTop,
            scrollHeight: scrollHeight,
            clientHeight: clientHeight,
            distanceToBottom: scrollHeight - scrollTop - clientHeight
        };
    }
""")

return result["distanceToBottom"] <= threshold
```

### 智能滚动

先检测是否到达底部，再决定是否滚动：

```python
if await is_at_page_bottom(page):
    return False

await page.evaluate(f"window.scrollBy(0, {distance})")
await asyncio.sleep(config.url_collector.scroll_delay)
return True
```

---

## 🔧 使用示例

### 基本使用

```python
import asyncio
from playwright.async_api import async_playwright
from autospider.extractor.collector.page_utils import is_at_page_bottom, smart_scroll

async def scroll_page():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        await page.goto("https://example.com")

        # 检测是否到达底部
        is_bottom = await is_at_page_bottom(page)
        print(f"是否到达底部: {is_bottom}")

        # 智能滚动
        for i in range(10):
            success = await smart_scroll(page, distance=500)
            if not success:
                print("已到达页面底部")
                break
            print(f"滚动 {i+1} 次")

        await browser.close()

# 运行
asyncio.run(scroll_page())
```

### 自定义阈值

```python
# 自定义底部检测阈值
is_bottom = await is_at_page_bottom(page, threshold=100)

# 自定义滚动距离
success = await smart_scroll(page, distance=1000)
```

---

## 📝 最佳实践

### 滚动控制

1. **使用智能滚动**：优先使用 `smart_scroll` 而不是直接滚动
2. **设置合理阈值**：根据页面高度设置合理的底部检测阈值
3. **检测滚动状态**：在滚动前检测是否已到达底部

### 性能优化

1. **避免过度滚动**：使用智能滚动避免无效滚动
2. **设置合理延迟**：在滚动后添加适当的延迟
3. **检测页面状态**：检测页面加载状态后再滚动

---

## 🔍 故障排除

### 常见问题

1. **底部检测不准确**
   - 检查页面是否已完全加载
   - 验证 JavaScript 执行是否正常
   - 确认阈值设置是否合理

2. **滚动失败**
   - 检查页面是否可滚动
   - 验证滚动距离是否合理
   - 确认页面是否已加载完成

### 调试技巧

```python
# 检查滚动状态
result = await page.evaluate("""
    () => {
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        const scrollHeight = document.documentElement.scrollHeight;
        const clientHeight = window.innerHeight;
        return {
            scrollTop: scrollTop,
            scrollHeight: scrollHeight,
            clientHeight: clientHeight,
            distanceToBottom: scrollHeight - scrollTop - clientHeight
        };
    }
""")

print(f"滚动位置: {result['scrollTop']}")
print(f"页面高度: {result['scrollHeight']}")
print(f"视口高度: {result['clientHeight']}")
print(f"距离底部: {result['distanceToBottom']}")
```

---

## 📚 函数参考

### 函数列表

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `is_at_page_bottom()` | page, threshold=50 | bool | 检测页面是否已经滚动到底部 |
| `smart_scroll()` | page, distance=500 | bool | 智能滚动页面 |

---

*最后更新: 2026-01-08*
