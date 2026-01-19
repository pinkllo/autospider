# Batch Field Extractor

`batch_field_extractor.py` 管理整个自动建模流程，从少量样本页中提取特征并推导出通用的采集模板。

---

## 🏗️ 核心类: `BatchFieldExtractor`

该类实现了从“手动/LLM 引导提取”到“全自动 XPath 提取”的转化过程。

### 工作阶段

#### 1. 探索阶段 (Exploration)
- 从 Redis 或给定列表中获取少量样本 URL（通常 3-5 个）。
- 使用 `FieldExtractor` 逐一提取字段。
- 收集每个样本页面中字段对应的精确 XPath。

#### 2. 分析阶段 (Analysis)
- 将收集到的样本 XPath 传递给 `FieldXPathExtractor`。
- 通过结构对齐算法，找出多个页面中该字段共有的结构特征。
- 生成 `CommonFieldXPath`。

#### 3. 校验阶段 (Validation)
- 使用新的样本 URL。
- **不使用 LLM**，直接使用分析阶段生成的公共 XPath 进行提取。
- 比较提取结果与预期（如数据类型是否匹配、是否为空）。
- 计算准确率。

---

## 🚀 核心方法

### `run(urls=None)` (async)
启动完整的批量提取、分析和校验流程。
- 返回 `BatchExtractionResult`。

### `_analyze_and_validate(exploration_records)` (async)
内部逻辑：基于探索记录进行分析并执行校验。
