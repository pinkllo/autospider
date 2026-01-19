# Field Extraction

Field Extraction 模块负责从详情页中自动识别并提取目标字段。它采用多阶段策略，结合 LLM 决策、SoM (Set of Mark) 视觉标记和模糊文本搜索，最终推导出稳定的 XPath 模式，用于后续的批量采集。

---

## 📁 模块结构

- `models.py`: 定义字段定义、提取结果、批量结果等数据结构。
- `field_extractor.py`: 核心提取器，负责单页字段提取。
- `batch_field_extractor.py`: 批量提取器，负责多页探索、分析、校验流程。
- `field_decider.py`: 封装 SoM + LLM 交互逻辑，辅助定位字段。
- `xpath_pattern.py`: 分析多个样本的 XPath，推导通用的公共 XPath 模式。
- `batch_xpath_extractor.py`: 基于公共 XPath 的批量快速提取器。

---

## 🛠️ 工作流程

1. **探索阶段 (Exploration)**:
   - 选取少量样本页面。
   - 对每个页面，使用 SoM + LLM 定位目标字段。
   - 提取字段文本，并记录其在页面中的 XPath。
2. **分析阶段 (Analysis)**:
   - 对探索阶段收集到的 XPath 进行模式匹配。
   - 推导出能够覆盖大多数页面的公共 XPath 模式。
3. **校验阶段 (Validation)**:
   - 选取另外的样本页面。
   - 使用生成的公共 XPath 进行提取，验证其准确性和通用性。
4. **配置生成**:
   - 如果验证通过，则生成包含公共 XPath 的提取配置。

---

## 🚀 快速开始

```python
from autospider.field.models import FieldDefinition
from autospider.field.batch_field_extractor import BatchFieldExtractor

# 1. 定义要提取的字段
fields = [
    FieldDefinition(name="title", description="文章标题"),
    FieldDefinition(name="price", description="商品价格", data_type="number"),
]

# 2. 初始化批量提取器
extractor = BatchFieldExtractor(page=page, fields=fields)

# 3. 运行流程
result = await extractor.run(urls=["http://example.com/p/1", "http://example.com/p/2"])

# 4. 获取生成的配置
config = result.to_extraction_config()
```
