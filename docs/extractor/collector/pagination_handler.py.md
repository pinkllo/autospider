# pagination_handler.py - 分页处理器

pagination_handler.py 模块提供分页处理功能，负责分页控件识别和翻页操作。

---

## 📁 文件路径

```
src/autospider/extractor/collector/pagination_handler.py
```

---

## 📑 函数目录

### 🚀 核心类
- `PaginationHandler` - 分页处理器主类

### 🔧 主要方法
- `extract_pagination_xpath()` - 提取分页控件的 xpath
- `extract_jump_widget_xpath()` - 提取跳转控件 xpath
- `find_and_click_next_page()` - 查找并点击下一页

---

## 🚀 核心功能

### PaginationHandler

分页处理器，负责识别和操作分页控件。

```python
from autospider.extractor.collector.pagination_handler import PaginationHandler

# 创建分页处理器
handler = PaginationHandler(
    page=page,
    list_url="https://example.com/list",
    screenshots_dir=screenshots_dir,
    llm_decision_maker=llm_decision_maker
)

# 提取分页控件 xpath
pagination_xpath = await handler.extract_pagination_xpath()

if pagination_xpath:
    print(f"分页控件 xpath: {pagination_xpath}")
    
    # 点击下一页
    success = await handler.find_and_click_next_page()
```

### 分页控件提取

使用 LLM 视觉识别和规则兜底提取分页控件：

```python
# 策略1: 优先使用 LLM 视觉识别
result = await self.extract_pagination_xpath_with_llm()

# 策略2: 使用规则兜底
if not result:
    result = await self.extract_pagination_xpath_with_rules()
```

### 跳转控件提取

提取跳转控件用于断点恢复：

```python
# 提取跳转控件
jump_widget_xpath = await handler.extract_jump_widget_xpath()

if jump_widget_xpath:
    print(f"跳转控件: {jump_widget_xpath}")
```

---

## 💡 特性说明

### LLM 视觉识别

优先使用 LLM 视觉识别分页控件：

```python
# 使用 LLM 视觉识别
result = await self.extract_pagination_xpath_with_llm()
```

### 规则兜底

LLM 识别失败时使用规则兜底：

```python
# 使用规则兜底
result = await self.extract_pagination_xpath_with_rules()
```

### 跳转控件

提取跳转控件用于断点恢复：

```python
# 提取跳转控件
jump_widget_xpath = {
    "input": "//input[@class='page-input']",
    "button": "//button[@class='jump-btn']"
}
```

---

## 🔧 使用示例

### 基本使用

```python
from autospider.extractor.collector.pagination_handler import PaginationHandler

# 创建分页处理器
handler = PaginationHandler(
    page=page,
    list_url="https://example.com/list",
    screenshots_dir="output/screenshots",
    llm_decision_maker=llm_decision_maker
)

# 提取分页控件 xpath
pagination_xpath = await handler.extract_pagination_xpath()

if pagination_xpath:
    print(f"分页控件 xpath: {pagination_xpath}")
    
    # 点击下一页
    for i in range(10):
        success = await handler.find_and_click_next_page()
        if not success:
            print("无法翻页，结束")
            break
        print(f"翻页成功: 第 {i+1} 页")
```

### 提取跳转控件

```python
# 提取跳转控件
jump_widget_xpath = await handler.extract_jump_widget_xpath()

if jump_widget_xpath:
    print(f"跳转控件输入框: {jump_widget_xpath['input']}")
    print(f"跳转控件按钮: {jump_widget_xpath['button']}")
```

---

## 📝 最佳实践

### 分页识别

1. **优先 LLM 识别**：优先使用 LLM 视觉识别
2. **使用规则兜底**：LLM 识别失败时使用规则兜底
3. **验证控件有效性**：验证提取的控件是否有效

### 翻页操作

1. **检测控件状态**：检测控件是否禁用
2. **处理翻页失败**：妥善处理翻页失败的情况
3. **记录翻页日志**：详细记录翻页过程便于调试

---

## 🔍 故障排除

### 常见问题

1. **分页控件识别失败**
   - 检查页面是否有分页控件
   - 验证 LLM 识别是否正确
   - 确认规则是否完善

2. **翻页失败**
   - 检查控件是否可点击
   - 验证控件选择器是否正确
   - 确认页面加载完成

---

## 📚 方法参考

### PaginationHandler 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `extract_pagination_xpath()` | 无 | str \| None | 提取分页控件的 xpath |
| `extract_jump_widget_xpath()` | 无 | dict \| None | 提取跳转控件 xpath |
| `find_and_click_next_page()` | 无 | bool | 查找并点击下一页 |

---

*最后更新: 2026-01-08*
