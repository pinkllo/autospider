# resume_strategy.py - 断点恢复策略

resume_strategy.py 模块实现三级断点定位策略，用于在爬虫中断后快速恢复到目标页。

---

## 📁 文件路径

```
src/autospider/crawler/checkpoint/resume_strategy.py
```

---

## 📑 函数目录

### 🚀 核心类
- `ResumeStrategy` - 恢复策略基类（抽象类）
- `URLPatternStrategy` - 策略一：URL 规律爆破
- `WidgetJumpStrategy` - 策略二：控件直达
- `SmartSkipStrategy` - 策略三：首项检测与回溯
- `ResumeCoordinator` - 恢复协调器

### 🔧 主要方法
- `try_resume()` - 尝试恢复到目标页
- `resume_to_page()` - 按优先级尝试恢复到目标页

### 🔍 内部方法
- `_detect_page_param()` - 检测 URL 中的页码参数名
- `_build_url_for_page()` - 构造目标页的 URL
- `_get_first_url()` - 获取列表页第一条数据的 URL
- `_click_next_page()` - 点击下一页
- `_click_prev_page()` - 点击上一页（用于回溯）

---

## 🚀 核心功能

### 三级断点定位策略

模块实现三级断点定位策略，按优先级尝试恢复：

**策略一：URL 规律爆破**
```python
# 分析列表页 URL 是否包含 page=xx 参数，直接构造跳转
strategy = URLPatternStrategy(list_url)
success, actual_page = await strategy.try_resume(page, target_page)
```

**策略二：控件直达**
```python
# 使用提取的跳转控件 xpath 进行跳转
strategy = WidgetJumpStrategy(jump_widget_xpath)
success, actual_page = await strategy.try_resume(page, target_page)
```

**策略三：首项检测与回溯**
```python
# 从第 1 页开始，只检测第一条数据，快速跳过已爬页面
strategy = SmartSkipStrategy(collected_urls, detail_xpath, pagination_xpath)
success, actual_page = await strategy.try_resume(page, target_page)
```

### ResumeCoordinator

恢复协调器，按优先级尝试各策略：

```python
from autospider.crawler.checkpoint.resume_strategy import ResumeCoordinator

# 创建恢复协调器
coordinator = ResumeCoordinator(
    list_url="https://example.com/list",
    collected_urls=set(collected_urls),
    jump_widget_xpath=jump_widget_xpath,
    detail_xpath=detail_xpath,
    pagination_xpath=pagination_xpath,
)

# 按优先级尝试恢复到目标页
actual_page = await coordinator.resume_to_page(page, target_page_num)
```

---

## 💡 特性说明

### 策略一：URL 规律爆破

分析列表页 URL 是否包含页码参数，直接构造跳转。

```python
class URLPatternStrategy(ResumeStrategy):
    """策略一: URL 规律爆破
    
    分析列表页 URL 是否包含 page=xx 参数，直接构造跳转。
    """
    
    def _detect_page_param(self) -> str | None:
        """检测 URL 中的页码参数名"""
        # 常见的页码参数名
        common_page_params = ["page", "p", "pageNum", "pageNo", "pn", "offset"]
        
        for param in common_page_params:
            if param in params:
                return param
        
        return None
```

**优点**：
- 最快速，直接构造 URL 跳转
- 不需要页面交互

**缺点**：
- 只适用于 URL 包含页码参数的网站
- 可能被服务器重定向

### 策略二：控件直达

使用提取的跳转控件 xpath 进行跳转。

```python
class WidgetJumpStrategy(ResumeStrategy):
    """策略二: 页码控件直达
    
    使用 Phase 3.6 提取的跳转控件 xpath 进行跳转。
    """
    
    async def try_resume(self, page: "Page", target_page: int) -> tuple[bool, int]:
        """尝试通过页码输入控件跳转"""
        # 清空并输入页码
        await input_locator.first.fill(str(target_page))
        
        # 点击确定按钮
        await button_locator.first.click()
```

**优点**：
- 适用于大多数分页网站
- 准确性高

**缺点**：
- 需要提前提取跳转控件 xpath
- 依赖页面结构稳定性

### 策略三：首项检测与回溯

从第 1 页开始，只检测第一条数据，快速跳过已爬页面。

```python
class SmartSkipStrategy(ResumeStrategy):
    """策略三: 首项检测与回溯 (兜底方案)
    
    从第 1 页开始，只检测第一条数据，快速跳过已爬页面。
    当检测到第一条新数据时，回退一页以确保完整性。
    """
    
    async def try_resume(self, page: "Page", target_page: int) -> tuple[bool, int]:
        """通过首项检测快速跳过已爬页面"""
        # 获取当前页第一条 URL
        first_url = await self._get_first_url(page)
        
        # 检查首条 URL 是否已存在
        if first_url in self.collected_urls:
            # 点击下一页
            await self._click_next_page(page)
        else:
            # 回溯一页以确保完整性
            if current_page > 1:
                await self._click_prev_page(page)
```

**优点**：
- 适用于所有分页网站
- 不依赖页面结构

**缺点**：
- 速度较慢，需要逐页检测
- 可能需要多次翻页

---

## 🔧 使用示例

### 使用恢复协调器

```python
import asyncio
from playwright.async_api import async_playwright
from autospider.crawler.checkpoint.resume_strategy import ResumeCoordinator

async def resume_collection():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # 创建恢复协调器
        coordinator = ResumeCoordinator(
            list_url="https://example.com/list",
            collected_urls=set(collected_urls),
            jump_widget_xpath={
                "input": "//input[@class='page-input']",
                "button": "//button[@class='jump-btn']"
            },
            detail_xpath="//a[@class='product-link']",
            pagination_xpath="//a[contains(text(),'下一页')]",
        )

        # 按优先级尝试恢复到目标页
        target_page_num = 10
        actual_page = await coordinator.resume_to_page(page, target_page_num)

        print(f"已恢复到第 {actual_page} 页")

        await browser.close()

# 运行
asyncio.run(resume_collection())
```

### 单独使用策略

```python
from autospider.crawler.checkpoint.resume_strategy import (
    URLPatternStrategy,
    WidgetJumpStrategy,
    SmartSkipStrategy
)

# 策略一：URL 规律爆破
strategy1 = URLPatternStrategy(list_url="https://example.com/list?page=1")
success, actual_page = await strategy1.try_resume(page, target_page=10)

# 策略二：控件直达
strategy2 = WidgetJumpStrategy(jump_widget_xpath={
    "input": "//input[@class='page-input']",
    "button": "//button[@class='jump-btn']"
})
success, actual_page = await strategy2.try_resume(page, target_page=10)

# 策略三：首项检测与回溯
strategy3 = SmartSkipStrategy(
    collected_urls=set(collected_urls),
    detail_xpath="//a[@class='product-link']",
    pagination_xpath="//a[contains(text(),'下一页')]"
)
success, actual_page = await strategy3.try_resume(page, target_page=10)
```

---

## 📝 最佳实践

### 策略选择

1. **优先使用策略一**：如果 URL 包含页码参数，优先使用 URL 规律爆破
2. **次选策略二**：如果已提取跳转控件 xpath，使用控件直达
3. **兜底策略三**：如果前两个策略都失败，使用首项检测与回溯

### 性能优化

1. **提前提取 xpath**：在探索阶段提取跳转控件 xpath
2. **缓存检测结果**：缓存首条 URL 检测结果
3. **限制跳过页数**：设置最大跳过页数避免无限循环

### 错误处理

1. **捕获异常**：妥善处理各种异常情况
2. **验证结果**：验证跳转是否成功
3. **记录日志**：详细记录恢复过程

---

## 🔍 故障排除

### 常见问题

1. **策略一失败**
   - 检查 URL 是否包含页码参数
   - 验证页码参数名是否正确
   - 确认 URL 构造是否正确

2. **策略二失败**
   - 检查跳转控件 xpath 是否正确
   - 验证控件是否存在且可见
   - 确认控件是否可交互

3. **策略三失败**
   - 检查详情页 xpath 是否正确
   - 验证分页控件 xpath 是否正确
   - 确认已收集 URL 集合是否正确

4. **所有策略失败**
   - 检查页面结构是否发生变化
   - 验证网络连接是否正常
   - 确认目标页码是否有效

### 调试技巧

```python
# 检查策略执行
for i, strategy in enumerate(coordinator.strategies, 1):
    print(f"策略 {i}: {strategy.name}")
    success, actual_page = await strategy.try_resume(page, target_page)
    print(f"  成功: {success}, 实际页: {actual_page}")

# 检查 URL 参数
parsed = urlparse(list_url)
params = parse_qs(parsed.query)
print(f"URL 参数: {params}")

# 检查首条 URL
first_url = await strategy._get_first_url(page)
print(f"首条 URL: {first_url}")
print(f"已收集: {first_url in collected_urls}")
```

---

## 📚 方法参考

### ResumeStrategy 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `try_resume()` | page, target_page | tuple[bool, int] | 尝试恢复到目标页 |

### URLPatternStrategy 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `_detect_page_param()` | 无 | str \| None | 检测 URL 中的页码参数名 |
| `_build_url_for_page()` | target_page | str \| None | 构造目标页的 URL |
| `try_resume()` | page, target_page | tuple[bool, int] | 尝试通过 URL 直接跳转 |

### WidgetJumpStrategy 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `try_resume()` | page, target_page | tuple[bool, int] | 尝试通过页码输入控件跳转 |

### SmartSkipStrategy 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `_get_first_url()` | page | str \| None | 获取列表页第一条数据的 URL |
| `_click_next_page()` | page | bool | 点击下一页 |
| `_click_prev_page()` | page | bool | 点击上一页（用于回溯） |
| `try_resume()` | page, target_page | tuple[bool, int] | 通过首项检测快速跳过已爬页面 |

### ResumeCoordinator 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `resume_to_page()` | page, target_page | int | 按优先级尝试恢复到目标页 |

---

*最后更新: 2026-01-08*
