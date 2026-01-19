# Fuzzy Text Search

`fuzzy_search.py` 提供了一种在 HTML 页面中通过文本内容定位元素的工具，特别适用于处理 LLM 输出文本与页面实际文本存在细微差异（如空格、大小写、特殊符号）的情况。

---

## 📁 模块信息

- **文件路径**: `src/autospider/common/utils/fuzzy_search.py`
- **依赖**: `lxml`, `difflib.SequenceMatcher`

---

## 📑 核心类与函数

### 🏗️ 数据模型

#### `TextMatch`
表示一个文本匹配结果。
- `text`: 页面中实际匹配到的文本。
- `similarity`: 相似度得分 (0.0 - 1.0)。
- `element_xpath`: 包含该文本的元素的 XPath。
- `element_tag`: 元素的 HTML 标签。
- `element_text_content`: 元素的完整文本内容。
- `position`: 在页面中的出现顺序（用于消歧）。

---

### 🔍 搜索器

#### `FuzzyTextSearcher`
主要的模糊搜索类。

**方法:**
- `__init__(threshold=0.8)`: 初始化搜索器，设置默认匹配阈值。
- `search_in_html(html_content, target_text, threshold=None)`: 在 HTML 中搜索目标文本，返回按相似度降序排列的 `TextMatch` 列表。

---

## 🛠️ 工作原理

1. **HTML 解析**: 使用 `lxml` 将 HTML 内容解析为树结构。
2. **文本提取**: 遍历树中的所有元素及其 `text` 和 `tail` 节点。
3. **相似度计算**:
   - **标准化**: 去除多余空格、转换为小写。
   - **完全匹配**: 相似度 1.0。
   - **子串包含**: 相似度 0.95。
   - **模糊匹配**: 使用 `SequenceMatcher` 计算编辑距离相似度。
4. **XPath 生成**: 为匹配到的元素生成尽可能唯一的 XPath（优先使用 ID）。

---

## 🚀 使用示例

```python
from autospider.common.utils.fuzzy_search import FuzzyTextSearcher

html = "<div><button id='btn1'>提交查询</button></div>"
searcher = FuzzyTextSearcher()

matches = searcher.search_in_html(html, "提交")
if matches:
    best_match = matches[0]
    print(f"找到匹配: {best_match.text} (相似度: {best_match.similarity})")
    print(f"XPath: {best_match.element_xpath}")
```
