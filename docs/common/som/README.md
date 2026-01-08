# SoM (Set-of-Mark) 子模块

SoM 子模块实现 Set-of-Mark 标注系统，为网页元素提供可视化标注和交互能力，是 AutoSpider 智能决策的核心组件。

---

## 📁 模块结构

```
src/autospider/common/som/
├── __init__.py              # 模块导出
├── api.py                   # SoM Python API
└── inject.js                # 浏览器注入脚本
```

---

## 📑 函数目录

### 🔧 SoM Python API (api.py)
- `inject_and_scan(page)` - 注入 SoM 脚本并扫描页面
- `capture_screenshot_with_marks(page)` - 带标注的截图
- `clear_overlay(page)` - 清除覆盖层
- `set_overlay_visibility(page, visible)` - 设置覆盖层可见性
- `get_element_by_mark_id(page, mark_id)` - 根据 mark_id 获取元素
- `build_mark_id_to_xpath_map(snapshot)` - 构建映射
- `format_marks_for_llm(snapshot, max_marks)` - 格式化标注信息

### 🎨 浏览器注入脚本 (inject.js)
- `injectSetOfMarks()` - 注入标注系统
- `getMarkedElements()` - 获取标注元素
- `highlightElement(markId)` - 高亮元素
- `removeAllMarks()` - 移除所有标注

---

## 🚀 核心功能

### SoM API 集成

SoMAPI 类提供与浏览器中 SoM 系统的交互接口，支持元素标注、信息获取和可视化操作。

```python
from autospider.common.som.api import inject_and_scan, build_mark_id_to_xpath_map

# 注入并扫描页面
snapshot = await inject_and_scan(page)

print(f"当前 URL: {snapshot.url}")
print(f"页面标题: {snapshot.title}")
print(f"发现 {len(snapshot.marks)} 个可交互元素")

# 打印所有标注
for mark in snapshot.marks:
    print(f"[{mark.mark_id}] {mark.tag}: {mark.text}")

# 构建 mark_id 到 XPath 的映射
xpath_map = build_mark_id_to_xpath_map(snapshot)
print(f"XPath 映射: {xpath_map}")
```

### 元素标注与识别

SoM 系统自动为页面中的可交互元素添加唯一标识，便于 LLM 进行精确的元素定位。

```python
# 获取元素的详细信息
for mark in snapshot.marks:
    print(f"标记ID: {mark.mark_id}")
    print(f"标签名: {mark.tag}")
    print(f"文本内容: {mark.text}")
    print(f"链接地址: {mark.href}")
    print(f"角色属性: {mark.role}")
    print(f"类名: {mark.class_name}")
    print(f"XPath候选: {mark.xpath_candidates}")

    # 检查元素是否可交互
    if mark.is_visible:
        print("元素可见")
    else:
        print("元素不可见")
```

---

## 💡 特性说明

### 标注系统原理

SoM 系统通过以下步骤实现元素标注：

1. **元素扫描**：扫描页面中的所有可交互元素
2. **唯一标识**：为每个元素分配唯一的 mark_id
3. **可视化标注**：在元素周围添加红色边框和编号
4. **信息收集**：收集元素的详细属性信息
5. **API 暴露**：通过 JavaScript API 提供访问接口

### 元素信息结构

每个标注元素包含丰富的属性信息：

```python
class ElementMark:
    mark_id: int                    # 唯一标识
    tag: str                       # 标签名
    text: str                      # 文本内容
    href: str                      # 链接地址
    role: str                      # 角色属性
    class_name: str                # CSS类名
    bounding_box: dict             # 位置信息
    xpath_candidates: List[dict]    # XPath候选
    is_interactive: bool           # 是否可交互
    is_visible: bool               # 是否可见
    attributes: dict               # 其他属性
```

### 智能元素过滤

支持基于多种条件的元素过滤：

```python
# 获取特定类型的元素
buttons = [m for m in snapshot.marks if m.tag == "button"]
links = [m for m in snapshot.marks if m.tag == "a"]
inputs = [m for m in snapshot.marks if m.tag == "input"]

# 基于文本内容过滤
search_elements = [m for m in snapshot.marks if "搜索" in m.text]
login_elements = [m for m in snapshot.marks if "登录" in m.text]

# 基于角色属性过滤
navigation_elements = [m for m in snapshot.marks if m.role == "navigation"]
main_content = [m for m in snapshot.marks if m.role == "main"]

# 组合过滤条件
important_elements = [
    m for m in snapshot.marks
    if m.is_interactive and m.is_visible and "重要" in m.text
]
```

---

## 🔧 使用示例

### 完整的页面分析流程

```python
import asyncio
from autospider.common.som.api import inject_and_scan, build_mark_id_to_xpath_map

async def analyze_page_with_som(page):
    """使用 SoM 系统分析页面"""

    # 注入并扫描页面
    snapshot = await inject_and_scan(page)

    print(f"页面中共有 {len(snapshot.marks)} 个可交互元素")

    # 分类统计元素
    element_stats = {
        "buttons": 0,
        "links": 0,
        "inputs": 0,
        "其他": 0
    }

    for mark in snapshot.marks:
        if mark.tag == "button":
            element_stats["buttons"] += 1
        elif mark.tag == "a":
            element_stats["links"] += 1
        elif mark.tag == "input":
            element_stats["inputs"] += 1
        else:
            element_stats["其他"] += 1

    print("元素分类统计:")
    for category, count in element_stats.items():
        print(f"  {category}: {count}")

    # 显示重要元素
    important_elements = [
        e for e in snapshot.marks
        if any(keyword in e.text.lower()
               for keyword in ["登录", "搜索", "下一步", "提交"])
    ]

    print(f"\n发现 {len(important_elements)} 个重要元素:")
    for element in important_elements:
        print(f"  [{element.mark_id}] {element.text} ({element.tag})")

    # 构建 XPath 映射
    xpath_map = build_mark_id_to_xpath_map(snapshot)
    print(f"\nXPath 映射: {xpath_map}")

    return snapshot, xpath_map

# 使用示例
async def main():
    # 假设已有页面实例
    page = await browser.new_page()
    await page.goto("https://example.com")

    snapshot, xpath_map = await analyze_page_with_som(page)

    # 可以根据分析结果进行后续操作
    if xpath_map:
        print(f"XPath 映射已生成，共 {len(xpath_map)} 个元素")

asyncio.run(main())
```

### 与 LLM 决策器集成

```python
import asyncio
from autospider.common.som.api import inject_and_scan, format_marks_for_llm

async def som_llm_integration(page, task_description):
    """SoM 与 LLM 决策器集成示例"""

    # 注入并扫描页面
    snapshot = await inject_and_scan(page)

    # 获取页面截图（包含 SoM 标注）
    screenshot_bytes, screenshot_base64 = await capture_screenshot_with_marks(page)

    # 获取标注元素信息
    marks_text = format_marks_for_llm(snapshot, max_marks=50)

    # 准备决策输入
    decision_input = {
        "screenshot": screenshot_base64,
        "marked_elements": marks_text,
        "task_description": task_description,
        "page_url": snapshot.url
    }

    print(f"标注信息:\n{marks_text}")

    # 这里可以调用 LLM 决策器
    # decision = await decider.decide(decision_input)

    return decision_input

# 使用示例
async def main():
    page = await browser.new_page()
    await page.goto("https://example.com")

    decision_input = await som_llm_integration(
        page,
        "找到登录按钮并点击"
    )

    print(f"决策输入已准备: {decision_input['page_url']}")

asyncio.run(main())
```

---

## 📝 最佳实践

### 标注策略

1. **选择性标注**：只标注真正可交互的元素
2. **唯一性保证**：确保每个元素的 mark_id 唯一
3. **稳定性**：页面刷新后保持标注一致性
4. **性能优化**：避免对大型页面过度标注

### 元素选择

1. **可见性优先**：优先选择可见的元素
2. **交互性检查**：确保元素真正可交互
3. **文本相关性**：基于任务目标选择相关元素
4. **位置考虑**：考虑元素在页面中的位置

### 错误处理

1. **元素不存在**：处理 mark_id 对应的元素不存在的情况
2. **页面变化**：处理页面动态变化导致的标注失效
3. **注入失败**：处理 SoM 脚本注入失败的情况
4. **兼容性**：处理不同浏览器的兼容性问题

---

## 🔍 故障排除

### 常见问题

1. **SoM 注入失败**
   - 检查页面是否完全加载
   - 验证注入脚本语法正确性
   - 确认浏览器支持情况

2. **元素标注不完整**
   - 检查元素选择逻辑
   - 验证 CSS 选择器有效性
   - 确认动态内容加载状态

3. **标注显示异常**
   - 检查 CSS 样式冲突
   - 验证元素位置计算
   - 确认页面布局稳定性

### 调试技巧

```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 检查注入状态
injection_status = await page.evaluate("window.__SOM__ !== undefined")
if injection_status:
    print("SoM 系统已成功注入")
else:
    print("SoM 注入失败")

# 获取详细的元素信息
for mark in snapshot.marks:
    print(f"元素 {mark.mark_id}:")
    print(f"  标签: {mark.tag}")
    print(f"  文本: {mark.text}")
    print(f"  XPath 候选: {[c.xpath for c in mark.xpath_candidates]}")
    print(f"  可见性: {mark.is_visible}")
    print(f"  位置: {mark.bbox}")
```

---

*最后更新: 2026-01-08*
