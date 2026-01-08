# mark_id_validator.py - mark_id 验证器

mark_id_validator.py 模块提供 mark_id 验证功能，用于验证 LLM 返回的 mark_id 与文本是否与实际的 SoM 元素匹配。

---

## 📁 文件路径

```
src/autospider/extractor/validator/mark_id_validator.py
```

---

## 📑 函数目录

### 🚀 核心类
- `MarkIdValidationResult` - mark_id 验证结果数据模型
- `MarkIdValidator` - mark_id 验证器主类

### 🔧 主要方法
- `validate_mark_id_text_map()` - 验证 LLM 返回的 mark_id 与文本映射

### 🔍 内部方法
- `_calculate_similarity()` - 计算两个文本的相似度
- `_normalize_text()` - 归一化文本
- `_extract_keywords()` - 提取关键词

---

## 🚀 核心功能

### MarkIdValidator

mark_id 验证器，验证 LLM 返回的 mark_id 与文本映射是否与实际的 SoM snapshot 匹配。

```python
from autospider.extractor.validator.mark_id_validator import MarkIdValidator

# 创建验证器
validator = MarkIdValidator()

# 验证 mark_id 与文本映射
valid_mark_ids, validation_results = validator.validate_mark_id_text_map(
    mark_id_text_map={"5": "商品名称", "10": "价格"},
    snapshot=snapshot
)

print(f"验证通过的 mark_id: {valid_mark_ids}")
print(f"验证结果数: {len(validation_results)}")
```

### 相似度计算

使用多种策略计算文本相似度：

```python
# 策略1：完全匹配
if norm1 == norm2:
    return 1.0

# 策略2：包含关系
if norm1 in norm2 or norm2 in norm1:
    length_ratio = shorter / longer
    return max(0.85, length_ratio)

# 策略3：SequenceMatcher
ratio = SequenceMatcher(None, norm1, norm2).ratio()

# 策略4：关键词重叠
keyword_overlap = len(intersection) / len(union)

# 综合打分
return ratio * 0.6 + keyword_overlap * 0.4
```

---

## 💡 特性说明

### 多策略相似度计算

使用多种策略计算文本相似度，提高准确性：

1. **完全匹配**：完全相同的文本返回 1.0
2. **包含关系**：一个文本是另一个的子串
3. **序列匹配**：使用 SequenceMatcher 计算相似度
4. **关键词重叠**：提取关键词并计算重叠度

### 文本归一化

归一化文本以提高匹配准确性：

```python
def _normalize_text(self, text: str) -> str:
    """归一化文本"""
    # 去除多余空格
    text = re.sub(r'\s+', ' ', text).strip()
    # 去除常见的装饰字符
    text = re.sub(r'[【】\[\]()（）《》<>「」『』""\'\'\"·•\-—_=+]', '', text)
    # 转小写
    return text.lower()
```

### 关键词提取

提取关键词用于相似度计算：

```python
def _extract_keywords(self, text: str) -> list[str]:
    """提取关键词（简化版，适用于中文）"""
    keywords = []
    
    # 提取中文词（2-4字的连续中文）
    chinese_pattern = re.compile(r'[\u4e00-\u9fff]{2,4}')
    keywords.extend(chinese_pattern.findall(text))
    
    # 提取英文单词
    english_pattern = re.compile(r'[a-zA-Z]{3,}')
    keywords.extend(english_pattern.findall(text.lower()))
    
    # 提取数字
    number_pattern = re.compile(r'\d{4,}')
    keywords.extend(number_pattern.findall(text))
    
    return keywords
```

---

## 🔧 使用示例

### 基本使用

```python
from autospider.extractor.validator.mark_id_validator import MarkIdValidator

# 创建验证器
validator = MarkIdValidator()

# 验证 mark_id 与文本映射
mark_id_text_map = {
    "5": "商品名称",
    "10": "价格",
    "15": "库存"
}

valid_mark_ids, validation_results = validator.validate_mark_id_text_map(
    mark_id_text_map=mark_id_text_map,
    snapshot=snapshot
)

print(f"验证通过的 mark_id: {valid_mark_ids}")
print(f"验证结果:")
for result in validation_results:
    print(f"  {result}")
```

### 自定义阈值

```python
# 自定义相似度阈值
validator = MarkIdValidator(threshold=0.8)

valid_mark_ids, validation_results = validator.validate_mark_id_text_map(
    mark_id_text_map,
    snapshot
)
```

### 启用调试模式

```python
# 启用调试模式，打印详细验证信息
validator = MarkIdValidator(debug=True)

valid_mark_ids, validation_results = validator.validate_mark_id_text_map(
    mark_id_text_map,
    snapshot
)
```

---

## 📝 最佳实践

### 验证策略

1. **设置合理阈值**：根据实际需求设置相似度阈值（通常 0.6-0.8）
2. **启用调试模式**：在开发时启用调试模式查看详细验证信息
3. **处理验证失败**：妥善处理验证失败的情况

### 文本处理

1. **归一化文本**：归一化文本以提高匹配准确性
2. **提取关键词**：提取关键词用于相似度计算
3. **多策略匹配**：使用多种策略提高匹配准确性

### 错误处理

1. **捕获异常**：妥善处理各种异常情况
2. **提供默认值**：在验证失败时提供默认值
3. **记录日志**：详细记录验证过程便于调试

---

## 🔍 故障排除

### 常见问题

1. **验证通过率低**
   - 检查阈值设置是否过高
   - 验证文本归一化是否正确
   - 确认相似度计算逻辑是否合理

2. **验证结果不准确**
   - 检查关键词提取是否正确
   - 验证相似度计算是否准确
   - 确认文本归一化是否完整

3. **性能问题**
   - 检查是否需要优化相似度计算
   - 验证是否可以缓存结果
   - 确认是否可以简化验证逻辑

### 调试技巧

```python
# 检查验证结果
for result in validation_results:
    print(f"mark_id: {result.mark_id}")
    print(f"LLM 文本: {result.llm_text}")
    print(f"实际文本: {result.actual_text}")
    print(f"相似度: {result.similarity:.2f}")
    print(f"是否通过: {result.is_valid}")
    print(f"元素: {result.element}")
    print("---")
```

---

## 📚 方法参考

### MarkIdValidator 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `validate_mark_id_text_map()` | mark_id_text_map, snapshot | tuple[list[int], list[MarkIdValidationResult]] | 验证 LLM 返回的 mark_id 与文本映射 |
| `_calculate_similarity()` | text1, text2 | float | 计算两个文本的相似度 |
| `_normalize_text()` | text | str | 归一化文本 |
| `_extract_keywords()` | text | list[str] | 提取关键词 |

### 初始化参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `threshold` | float | 从配置读取 | 相似度阈值 |
| `debug` | bool | 从配置读取 | 是否打印调试信息 |

---

*最后更新: 2026-01-08*
