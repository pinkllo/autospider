# Browser Manager

Browser Manager 模块负责管理浏览器实例的生命周期和交互操作，提供统一的浏览器控制接口。

---

## 📁 模块结构

```
common/browser_manager/
├── __init__.py              # 模块导出
├── engine.py                # 浏览器引擎管理
└── interaction.py           # 浏览器交互操作
```

---

## 📑 函数目录

### 🚀 浏览器引擎管理 (engine.py)
- `BrowserEngine` - 浏览器引擎主类
- `create_browser()` - 创建浏览器实例
- `close_browser()` - 关闭浏览器实例
- `get_browser_context()` - 获取浏览器上下文

### 🖱️ 浏览器交互操作 (interaction.py)
- `BrowserInteraction` - 浏览器交互控制器
- `navigate_to(url)` - 导航到指定URL
- `click_element(selector)` - 点击页面元素
- `type_text(selector, text)` - 输入文本
- `scroll_page(distance)` - 滚动页面
- `take_screenshot()` - 截取页面截图

---

## 🚀 核心功能

### 浏览器引擎管理

BrowserEngine 类负责管理浏览器实例的完整生命周期，包括创建、配置和销毁。

```python
from common.browser_manager.engine import BrowserEngine

# 创建浏览器引擎
engine = BrowserEngine(
    headless=False,          # 是否无头模式
    viewport_width=1280,     # 视口宽度
    viewport_height=720,     # 视口高度
    slow_mo=100             # 慢动作模式（毫秒）
)

# 启动浏览器
await engine.start()

# 获取浏览器上下文
context = engine.get_context()

# 关闭浏览器
await engine.close()
```

### 浏览器交互操作

BrowserInteraction 类封装了常见的浏览器操作，提供简洁的API进行页面交互。

```python
from common.browser_manager.interaction import BrowserInteraction

# 创建交互控制器
interaction = BrowserInteraction(engine)

# 导航到页面
await interaction.navigate_to("https://example.com")

# 点击元素
await interaction.click_element("button.submit")

# 输入文本
await interaction.type_text("input.search", "AutoSpider")

# 滚动页面
await interaction.scroll_page(500)

# 截取截图
screenshot = await interaction.take_screenshot()
```

---

## 💡 特性说明

### 浏览器配置选项

支持丰富的浏览器配置选项，满足不同场景的需求：

```python
from common.browser_manager.engine import BrowserEngine

# 完整配置示例
engine = BrowserEngine(
    headless=True,              # 无头模式
    viewport_width=1920,        # 视口宽度
    viewport_height=1080,       # 视口高度
    slow_mo=50,                 # 操作延迟
    timeout=30000,              # 超时时间
    user_agent="Mozilla/5.0...", # 自定义User-Agent
    ignore_https_errors=True    # 忽略HTTPS错误
)
```

### 智能等待机制

内置智能等待机制，确保页面元素加载完成后再执行操作：

```python
# 等待元素出现
await interaction.wait_for_selector(".loading", timeout=10000)

# 等待页面加载完成
await interaction.wait_for_load_state("networkidle")

# 自定义等待条件
await interaction.wait_for_function(
    "() => document.readyState === 'complete'"
)
```

### 错误处理与重试

提供完善的错误处理机制和自动重试功能：

```python
try:
    # 尝试操作，失败时自动重试
    await interaction.click_element_with_retry(
        "button.submit",
        max_retries=3,
        retry_delay=1000
    )
except TimeoutError:
    print("操作超时")
except ElementNotFoundError:
    print("元素未找到")
```

---

## 🔧 使用示例

### 完整的浏览器自动化流程

```python
import asyncio
from common.browser_manager.engine import BrowserEngine
from common.browser_manager.interaction import BrowserInteraction

async def automate_browser():
    """完整的浏览器自动化示例"""

    # 创建浏览器引擎
    engine = BrowserEngine(headless=False)

    try:
        # 启动浏览器
        await engine.start()

        # 创建交互控制器
        interaction = BrowserInteraction(engine)

        # 导航到目标页面
        await interaction.navigate_to("https://example.com/login")

        # 登录操作
        await interaction.type_text("#username", "testuser")
        await interaction.type_text("#password", "testpass")
        await interaction.click_element("#login-btn")

        # 等待登录完成
        await interaction.wait_for_selector(".dashboard")

        # 执行数据采集
        await interaction.navigate_to("https://example.com/products")

        # 滚动加载更多内容
        for _ in range(3):
            await interaction.scroll_page(800)
            await asyncio.sleep(1)

        # 截取最终页面
        screenshot = await interaction.take_screenshot()

        return screenshot

    finally:
        # 确保浏览器关闭
        await engine.close()

# 运行自动化任务
result = asyncio.run(automate_browser())
```

### 多页面并发处理

```python
import asyncio
from common.browser_manager.engine import BrowserEngine

async def process_multiple_pages(urls):
    """并发处理多个页面"""

    # 创建浏览器引擎
    engine = BrowserEngine(headless=True)
    await engine.start()

    async def process_url(url):
        """处理单个URL"""
        page = await engine.new_page()

        try:
            await page.goto(url)

            # 执行页面操作
            content = await page.content()
            screenshot = await page.screenshot()

            return {
                'url': url,
                'content': content,
                'screenshot': screenshot
            }
        finally:
            await page.close()

    # 并发处理所有URL
    tasks = [process_url(url) for url in urls]
    results = await asyncio.gather(*tasks)

    await engine.close()
    return results

# 使用示例
urls = [
    "https://example.com/page1",
    "https://example.com/page2",
    "https://example.com/page3"
]

results = asyncio.run(process_multiple_pages(urls))
```

---

## 📝 最佳实践

### 资源管理

1. **及时关闭**：确保浏览器实例在使用后正确关闭
2. **异常处理**：使用 try-finally 块确保资源释放
3. **连接池**：对于高并发场景，考虑使用连接池

### 性能优化

1. **无头模式**：生产环境使用无头模式提高性能
2. **资源限制**：合理设置视口大小和超时时间
3. **并发控制**：避免过多的并发浏览器实例

### 反爬虫策略

1. **User-Agent轮换**：定期更换User-Agent
2. **操作延迟**：添加随机延迟模拟人类行为
3. **IP轮换**：结合代理IP使用

---

## 🔍 故障排除

### 常见问题

1. **浏览器启动失败**
   - 检查浏览器是否已安装
   - 验证浏览器路径配置
   - 检查系统权限

2. **页面加载超时**
   - 增加超时时间设置
   - 检查网络连接
   - 验证目标URL可访问性

3. **元素定位失败**
   - 确认选择器正确性
   - 检查元素是否在iframe中
   - 验证页面加载状态

### 调试技巧

```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 使用慢动作模式观察操作
engine = BrowserEngine(slow_mo=500, headless=False)

# 保存操作日志
await interaction.enable_logging("browser_operations.log")
```

---

*最后更新: 2026-01-08*
