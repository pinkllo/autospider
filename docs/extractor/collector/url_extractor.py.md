# url_extractor.py - URL 提取器

url_extractor.py 模块提供 URL 提取功能，负责从元素中提取 URL。

---

## 📁 文件路径

```
src/autospider/extractor/collector/url_extractor.py
```

---

## 📑 函数目录

### 🚀 核心类
- `URLExtractor` - URL 提取器主类

### 🔧 主要方法
- `extract_from_element()` - 从元素中提取 URL
- `click_and_get_url()` - 点击元素并获取新页面的 URL
- `click_element_and_get_url()` - 点击 locator 并获取 URL

---

## 🚀 核心功能

### URLExtractor

URL 提取器，负责从页面元素中提取详情页 URL。

```python
from autospider.extractor.collector.url_extractor import URLExtractor

# 创建 URL 提取器
extractor = URLExtractor(page, list_url)

# 从元素中提取 URL
url = await extractor.extract_from_element(
    element=element,
    snapshot=snapshot,
    nav_steps=nav_steps
)

print(f"提取的 URL: {url}")
```

### 提取策略

使用两种策略提取 URL：

**策略 1: 从 href 提取**
```python
if element.href:
    url = urljoin(self.list_url, element.href)
    return url
```

**策略 2: 点击获取**
```python
url = await self.click_and_get_url(element, nav_steps=nav_steps)
return url
```

---

## 💡 特性说明

### 优先从 href 提取

优先从元素的 href 属性提取 URL，避免不必要的点击：

```python
if element.href:
    url = urljoin(self.list_url, element.href)
    print(f"✓ 从 href 提取: {url[:60]}...")
    return url
```

### 新标签页检测

自动检测新标签页的打开：

```python
context = self.page.context
pages_before = len(context.pages)

# 点击元素
await element.click()

# 检查是否有新标签页打开
pages_after = len(context.pages)
if pages_after > pages_before:
    new_page = context.pages[-1]
    url = new_page.url
```

### 导航步骤重放

在返回列表页时重放导航步骤：

```python
# 返回列表页
await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)

# 重放导航步骤
if nav_steps:
    for step in nav_steps:
        # 执行导航步骤
        pass
```

---

## 🔧 使用示例

### 基本使用

```python
from autospider.extractor.collector.url_extractor import URLExtractor

# 创建 URL 提取器
extractor = URLExtractor(page, list_url="https://example.com/list")

# 从元素中提取 URL
url = await extractor.extract_from_element(
    element=element,
    snapshot=snapshot,
    nav_steps=[]
)

print(f"提取的 URL: {url}")
```

### 点击获取 URL

```python
# 点击元素并获取 URL
url = await extractor.click_and_get_url(
    element=element,
    nav_steps=nav_steps
)

print(f"点击后获取的 URL: {url}")
```

### 使用 locator

```python
# 使用 locator 提取 URL
locator = page.locator("//a[@class='product-link']")

url = await extractor.click_element_and_get_url(
    locator=locator,
    nav_steps=nav_steps
)

print(f"提取的 URL: {url}")
```

---

## 📝 最佳实践

### URL 提取

1. **优先使用 href**：优先从 href 属性提取 URL
2. **验证 URL 有效性**：验证提取的 URL 是否有效
3. **处理相对路径**：正确处理相对路径转换为绝对路径

### 新标签页处理

1. **检测新标签页**：自动检测新标签页的打开
2. **切换到新标签页**：自动切换到新标签页
3. **关闭旧标签页**：根据需要关闭旧标签页

### 导航步骤重放

1. **保存导航步骤**：保存导航步骤以便重放
2. **重放导航步骤**：在返回列表页时重放导航步骤
3. **验证重放结果**：验证导航步骤重放是否成功

---

## 🔍 故障排除

### 常见问题

1. **URL 提取失败**
   - 检查元素是否有 href 属性
   - 验证元素是否可点击
   - 确认页面加载完成

2. **新标签页处理失败**
   - 检查新标签页是否正确打开
   - 验证标签页切换逻辑是否正确
   - 确认 URL 是否正确获取

3. **导航步骤重放失败**
   - 检查导航步骤是否正确
   - 验证元素选择器是否有效
   - 确认页面状态是否正确

### 调试技巧

```python
# 检查元素信息
print(f"元素 tag: {element.tag}")
print(f"元素 text: {element.text}")
print(f"元素 href: {element.href}")
print(f"元素 role: {element.role}")

# 检查提取的 URL
print(f"提取的 URL: {url}")
print(f"URL 长度: {len(url)}")

# 检查页面状态
print(f"当前 URL: {page.url}")
print(f"标签页数: {len(page.context.pages)}")
```

---

## 📚 方法参考

### URLExtractor 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `extract_from_element()` | element, snapshot, nav_steps | str \| None | 从元素中提取 URL |
| `click_and_get_url()` | element, nav_steps | str \| None | 点击元素并获取新页面的 URL |
| `click_element_and_get_url()` | locator, nav_steps | str \| None | 点击 locator 并获取 URL |

---

*最后更新: 2026-01-08*
