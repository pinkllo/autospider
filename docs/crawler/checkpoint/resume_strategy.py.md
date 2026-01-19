# Resume Strategy - 断点恢复策略

## 📋 基本信息

### 文件路径
`d:\autospider\src\autospider\crawler\checkpoint\resume_strategy.py`

### 核心功能
实现三级断点定位策略，用于从上次中断的位置恢复收集任务：
1. **URLPatternStrategy** - URL 规律爆破，直接构造目标页 URL
2. **WidgetJumpStrategy** - 控件直达，使用页码输入控件跳转
3. **SmartSkipStrategy** - 首项检测与回溯，快速跳过已爬页面

### 设计理念
采用策略模式，按优先级尝试不同的恢复策略，确保在各种情况下都能尽可能恢复到正确的断点位置。

## 📁 函数目录

### 辅助函数
- `_is_xpath_selector` - 检查是否为 XPath 选择器
- `_build_locator` - 构建 Playwright 定位器

### 抽象基类
- `ResumeStrategy` - 恢复策略基类

### 策略实现类
- `URLPatternStrategy` - URL 规律爆破策略
- `WidgetJumpStrategy` - 控件直达策略
- `SmartSkipStrategy` - 首项检测回溯策略

### 协调器类
- `ResumeCoordinator` - 恢复协调器，按优先级尝试各策略

## 🎯 核心功能详解

### ResumeStrategy 抽象基类

**功能说明**：恢复策略基类，定义了策略的接口。

**核心方法**：
- `name` - 抽象属性，返回策略名称
- `try_resume` - 抽象方法，尝试恢复到目标页

### URLPatternStrategy 类

**功能说明**：URL 规律爆破策略，分析列表页 URL 是否包含 page=xx 参数，直接构造跳转。

**初始化参数**：
| 参数名 | 类型 | 描述 | 默认值 |
|--------|------|------|--------|
| list_url | `str` | 列表页 URL | 必填 |

**核心方法**：
- `_detect_page_param` - 检测 URL 中的页码参数名
- `_build_url_for_page` - 构造目标页的 URL
- `try_resume` - 尝试通过 URL 直接跳转

**支持的页码参数**：
- 常见页码参数：page, p, pageNum, pageNo, pn, offset
- 自动检测 URL 中的页码参数
- 直接构造目标页 URL 进行跳转

### WidgetJumpStrategy 类

**功能说明**：控件直达策略，使用页码输入控件进行跳转。

**初始化参数**：
| 参数名 | 类型 | 描述 | 默认值 |
|--------|------|------|--------|
| jump_widget_xpath | `dict[str, str] | None` | 跳转控件 XPath，格式为 `{"input": "xpath", "button": "xpath"}` | None |

**核心方法**：
- `try_resume` - 尝试通过页码输入控件跳转

**工作流程**：
1. 定位页码输入框
2. 清空并输入目标页码
3. 点击确定按钮
4. 等待页面加载

### SmartSkipStrategy 类

**功能说明**：首项检测回溯策略，从第 1 页开始，只检测第一条数据，快速跳过已爬页面。

**初始化参数**：
| 参数名 | 类型 | 描述 | 默认值 |
|--------|------|------|--------|
| collected_urls | `set[str]` | 已收集的 URL 集合 | 必填 |
| detail_xpath | `str | None` | 详情页链接的 XPath | None |
| pagination_xpath | `str | None` | 下一页按钮的 XPath | None |

**核心方法**：
- `_get_first_url` - 获取列表页第一条数据的 URL
- `_click_next_page` - 点击下一页
- `_click_prev_page` - 点击上一页（用于回溯）
- `try_resume` - 通过首项检测快速跳过已爬页面

**工作流程**：
1. 从第 1 页开始，获取每页第一条 URL
2. 检查首条 URL 是否已存在
3. 如果已存在，快速跳转到下一页
4. 当检测到第一条新数据时，回退一页以确保完整性
5. 返回正确的恢复页码

### ResumeCoordinator 类

**功能说明**：恢复协调器，按优先级尝试各策略。

**初始化参数**：
| 参数名 | 类型 | 描述 | 默认值 |
|--------|------|------|--------|
| list_url | `str` | 列表页 URL | 必填 |
| collected_urls | `set[str]` | 已收集的 URL 集合 | 必填 |
| jump_widget_xpath | `dict[str, str] | None` | 跳转控件 XPath | None |
| detail_xpath | `str | None` | 详情页链接 XPath | None |
| pagination_xpath | `str | None` | 分页控件 XPath | None |

**核心方法**：
- `resume_to_page` - 按优先级尝试恢复到目标页

**策略优先级**：
1. URLPatternStrategy（最快，直接 URL 跳转）
2. WidgetJumpStrategy（中等，控件跳转）
3. SmartSkipStrategy（兜底，首项检测）

## 🚀 特性说明

### 多级恢复策略
- 支持三种不同的恢复策略
- 按优先级自动尝试
- 确保在各种情况下都能恢复

### 智能 URL 分析
- 自动检测 URL 中的页码参数
- 支持多种常见的页码参数名
- 直接构造目标页 URL，跳过中间页面

### 控件智能定位
- 支持 XPath 选择器
- 自动识别页码输入框和确定按钮
- 智能处理控件不可用情况

### 高效首项检测
- 只检测每页第一条数据，快速跳过已爬页面
- 当检测到新数据时，自动回溯一页以确保完整性
- 防止无限循环，设置最大跳过页数

### 灵活的 XPath 支持
- 支持多种 XPath 格式
- 自动处理不同的选择器类型
- 兼容各种页面结构

## 💡 使用示例

### 基本使用

```python
from playwright.async_api import async_playwright
from autospider.crawler.checkpoint.resume_strategy import ResumeCoordinator

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        # 导航到列表页
        await page.goto("https://example.com/products?page=1")
        
        # 创建恢复协调器
        coordinator = ResumeCoordinator(
            list_url="https://example.com/products?page=1",
            collected_urls={"https://example.com/product/1", "https://example.com/product/2"},
            detail_xpath="//a[@class='product-link']",
            pagination_xpath="//a[contains(text(), '下一页')]"
        )
        
        # 恢复到第 5 页
        actual_page = await coordinator.resume_to_page(page, 5)
        
        print(f"实际恢复到第 {actual_page} 页")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
```

### 使用特定策略

```python
from playwright.async_api import async_playwright
from autospider.crawler.checkpoint.resume_strategy import URLPatternStrategy

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        # 导航到列表页
        await page.goto("https://example.com/products?page=1")
        
        # 创建 URL 规律爆破策略
        strategy = URLPatternStrategy("https://example.com/products?page=1")
        
        # 尝试恢复到第 5 页
        success, actual_page = await strategy.try_resume(page, 5)
        
        if success:
            print(f"成功恢复到第 {actual_page} 页")
        else:
            print("恢复失败")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
```

## 🔍 最佳实践

### 策略选择建议

1. **URLPatternStrategy**：适合 URL 中包含明确页码参数的网站
   - 优点：速度最快，直接跳转
   - 缺点：依赖 URL 结构

2. **WidgetJumpStrategy**：适合有页码输入框的网站
   - 优点：准确可靠
   - 缺点：需要配置跳转控件 XPath

3. **SmartSkipStrategy**：适合各种网站，作为兜底策略
   - 优点：通用性强，不需要特殊配置
   - 缺点：速度较慢，需要逐个页面跳过

### 配置建议

- 确保提供准确的详情页链接 XPath
- 确保提供准确的分页控件 XPath
- 对于有跳转控件的网站，建议配置 WidgetJumpStrategy
- 对于 URL 结构清晰的网站，URLPatternStrategy 是最佳选择

### 性能优化

- 优先使用 URLPatternStrategy，速度最快
- SmartSkipStrategy 可以设置最大跳过页数，防止无限循环
- 合理设置页面加载等待时间

## 🐛 故障排除

### 问题：URLPatternStrategy 失败

**可能原因**：
1. URL 中没有页码参数
2. 页码参数名不在支持列表中
3. 网站有反爬机制，阻止直接 URL 跳转

**解决方案**：
1. 检查 URL 结构，确认是否有页码参数
2. 手动指定页码参数名
3. 尝试使用其他恢复策略

### 问题：WidgetJumpStrategy 失败

**可能原因**：
1. 跳转控件 XPath 配置错误
2. 页面结构发生变化
3. 控件被动态加载
4. 网站有反爬机制，阻止控件操作

**解决方案**：
1. 重新定位跳转控件，更新 XPath
2. 增加等待时间，确保控件加载完成
3. 尝试使用其他恢复策略

### 问题：SmartSkipStrategy 速度缓慢

**可能原因**：
1. 已收集的 URL 数量太多
2. 页面加载时间过长
3. 最大跳过页数设置过大

**解决方案**：
1. 合理设置最大跳过页数
2. 优化页面加载等待时间
3. 考虑使用其他恢复策略

## 📚 方法参考

### 辅助函数

| 函数名 | 参数 | 返回值 | 描述 |
|--------|------|--------|------|
| `_is_xpath_selector` | selector | `bool` | 检查是否为 XPath 选择器 |
| `_build_locator` | page, selector | `Locator | None` | 构建 Playwright 定位器 |

### ResumeStrategy 抽象方法

| 方法名 | 参数 | 返回值 | 描述 |
|--------|------|--------|------|
| `try_resume` | page, target_page | `tuple[bool, int]` | 尝试恢复到目标页 |

### ResumeCoordinator 方法

| 方法名 | 参数 | 返回值 | 描述 |
|--------|------|--------|------|
| `resume_to_page` | page, target_page | `int` | 按优先级尝试恢复到目标页 |

## 🔄 依赖关系

- `Playwright` - 用于页面操作和定位
- `urllib.parse` - 用于 URL 解析和构造

## 📝 设计模式

- **策略模式**：定义了多种恢复策略，按优先级尝试
- **抽象基类模式**：定义了策略的统一接口
- **协调器模式**：管理和协调不同的恢复策略

## 🚀 性能优化

### 时间复杂度
- URLPatternStrategy：O(1)，直接 URL 跳转
- WidgetJumpStrategy：O(1)，直接控件跳转
- SmartSkipStrategy：O(N)，其中 N 是已爬页面数量

### 空间复杂度
- O(1)，不占用额外空间

### 优化建议

1. 优先使用 URLPatternStrategy，速度最快
2. 合理配置 WidgetJumpStrategy，准确可靠
3. SmartSkipStrategy 作为兜底，设置最大跳过页数
4. 合理设置页面加载等待时间

## 📌 版本历史

| 版本 | 更新内容 | 日期 |
|------|----------|------|
| 1.0 | 初始版本，实现三种恢复策略 | 2026-01-01 |
| 1.1 | 优化 URL 分析算法 | 2026-01-10 |
| 1.2 | 增强控件定位功能 | 2026-01-15 |
| 1.3 | 优化首项检测算法，增加回溯机制 | 2026-01-18 |

## 🔮 未来规划

- 支持更多类型的 URL 模式
- 增强控件智能识别能力
- 优化首项检测算法，提高速度
- 支持更多类型的分页控件
- 增加恢复策略的可配置性

## 📄 许可证

MIT License

---

最后更新: 2026-01-19