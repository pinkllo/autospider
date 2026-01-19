# Field Models

`models.py` 定义了字段提取过程中使用的核心数据结构，采用 `dataclass` 实现。

---

## 📑 核心模型

### `FieldDefinition`
描述要提取的目标字段。
- `name`: 字段内部名称（如 `title`）。
- `description`: 字段的自然语言描述，帮助 LLM 理解（如 `招标公告的发布日期`）。
- `required`: 是否为必填项。
- `data_type`: 预期数据类型（`text`, `number`, `date`, `url`）。
- `example`: 示例值，用于引导 LLM 提取。

### `FieldExtractionResult`
记录单个字段的单次提取结果。
- `field_name`: 字段名称。
- `value`: 提取到的原始文本值。
- `xpath`: 提取该值所用的具体 XPath。
- `confidence`: 提取的置信度。
- `extraction_method`: 提取方法（`llm`, `xpath`, `fuzzy_search`）。

### `PageExtractionRecord`
记录从单个页面提取所有字段的完整信息。
- `url`: 页面地址。
- `fields`: 该页面所有字段的 `FieldExtractionResult` 列表。
- `success`: 是否成功提取了所有必填字段。

### `CommonFieldXPath`
表示经过分析推导出的公共 XPath 模式。
- `field_name`: 字段名称。
- `xpath_pattern`: 推导出的通用 XPath 模式。
- `validated`: 是否已通过验证。

### `BatchExtractionResult`
记录整个批量提取任务的结果，包括探索记录、推导出的公共 XPath 以及验证记录。
- `to_extraction_config()`: 将结果转换为可用于后续爬取的 JSON 配置。
