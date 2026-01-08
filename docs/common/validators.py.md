# validators.py - 验证器

validators.py 模块提供数据验证功能，用于验证用户输入和系统配置的有效性。

---

## 📁 文件路径

```
src/autospider/common/validators.py
```

---

## 📑 函数目录

### ✅ 验证函数
- `validate_url(url)` - 验证 URL 格式
- `validate_email(email)` - 验证邮箱格式
- `validate_xpath(xpath)` - 验证 XPath 语法
- `validate_mark_id(mark_id)` - 验证 mark_id 有效性

---

## 🚀 核心功能

### URL 验证

验证 URL 格式是否正确。

```python
from autospider.common.validators import validate_url

url = "https://example.com"
is_valid = validate_url(url)

if is_valid:
    print(f"URL 有效: {url}")
else:
    print(f"URL 无效: {url}")
```

### XPath 验证

验证 XPath 语法是否正确。

```python
from autospider.common.validators import validate_xpath

xpath = "//button[@id='login']"
is_valid = validate_xpath(xpath)

if is_valid:
    print(f"XPath 有效: {xpath}")
else:
    print(f"XPath 无效: {xpath}")
```

---

## 💡 特性说明

### 多种验证类型

支持多种数据类型的验证：

```python
# URL 验证
validate_url("https://example.com")

# 邮箱验证
validate_email("user@example.com")

# XPath 验证
validate_xpath("//div[@class='content']")

# mark_id 验证
validate_mark_id(5)
```

### 错误信息

验证失败时提供详细的错误信息：

```python
from autospider.common.validators import validate_url

try:
    validate_url("invalid-url")
except ValidationError as e:
    print(f"验证失败: {e.message}")
    print(f"错误代码: {e.code}")
```

---

## 🔧 使用示例

### 完整的验证流程

```python
from autospider.common.validators import (
    validate_url,
    validate_email,
    validate_xpath,
    validate_mark_id
)

# 验证 URL
url = "https://example.com"
if validate_url(url):
    print(f"URL 验证通过: {url}")

# 验证邮箱
email = "user@example.com"
if validate_email(email):
    print(f"邮箱验证通过: {email}")

# 验证 XPath
xpath = "//button[@id='login']"
if validate_xpath(xpath):
    print(f"XPath 验证通过: {xpath}")

# 验证 mark_id
mark_id = 5
if validate_mark_id(mark_id):
    print(f"mark_id 验证通过: {mark_id}")
```

---

## 📝 最佳实践

### 验证策略

1. **早期验证**：在数据处理前进行验证
2. **详细错误**：提供清晰的错误信息
3. **批量验证**：支持批量数据验证
4. **性能优化**：避免重复验证

### 错误处理

1. **异常捕获**：捕获并处理验证异常
2. **错误日志**：记录验证失败信息
3. **用户提示**：提供友好的错误提示
4. **恢复建议**：给出修复建议

---

## 🔍 故障排除

### 常见问题

1. **验证失败**
   - 检查数据格式是否正确
   - 验证验证规则是否合理
   - 确认输入数据是否完整

2. **性能问题**
   - 优化验证逻辑
   - 使用缓存避免重复验证
   - 批量处理数据

### 调试技巧

```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 检查验证结果
try:
    validate_url("https://example.com")
    print("验证成功")
except Exception as e:
    print(f"验证失败: {e}")
```

---

*最后更新: 2026-01-08*
