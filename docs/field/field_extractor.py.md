# Field Extractor

`field_extractor.py` 是详情页字段提取的核心执行单元，负责从单个 URL 中提取所有定义的字段。

---

## 🏗️ 核心类: `FieldExtractor`

该类集成了多种提取技术，确保在复杂的动态网页中也能准确获取数据。

### 初始化参数
- `page`: Playwright `Page` 实例。
- `fields`: `FieldDefinition` 列表。
- `max_nav_steps`: 每个字段尝试导航的最大步数。

### 核心逻辑
1. **SoM 注入**: 在页面上注入 Set of Mark (SoM) 脚本，标记所有可见元素。
2. **视觉感知**: 截取带标记的屏幕截图。
3. **LLM 决策**: 将截图、标记信息和字段定义发送给 LLM，由 LLM 决定哪个标记 ID 对应目标字段。
4. **模糊搜索辅助**: 如果 LLM 提取了文本但未提供标记 ID，提取器会使用 `FuzzyTextSearcher` 在 HTML 中模糊匹配文本并定位元素 XPath。
5. **消歧与验证**: 自动处理多个相似匹配项，并验证提取到的值是否符合字段定义。

---

## 📑 主要方法

### `run(url)` (async)
对指定 URL 执行完整的提取流程。
- 返回 `PageExtractionRecord`。

### `_extract_single_field(field_def)` (async)
提取单个字段的内部逻辑，包括多轮导航和尝试。
