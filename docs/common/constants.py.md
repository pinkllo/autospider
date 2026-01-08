# constants.py - 常量定义

constants.py 模块定义 AutoSpider 项目使用的常量，包括系统配置、错误代码、超时时间等。

---

## 📁 文件路径

```
src/autospider/common/constants.py
```

---

## 📑 常量目录

### ⏱️ 超时配置
- `DEFAULT_TIMEOUT_MS` - 默认超时时间
- `PAGE_LOAD_TIMEOUT_MS` - 页面加载超时时间
- `ELEMENT_WAIT_TIMEOUT_MS` - 元素等待超时时间

### 🔄 重试配置
- `MAX_RETRIES` - 最大重试次数
- `RETRY_DELAY_MS` - 重试延迟时间

### 📊 性能配置
- `MAX_CONCURRENT_REQUESTS` - 最大并发请求数
- `BATCH_SIZE` - 批处理大小

### 🔧 系统配置
- `DEFAULT_VIEWPORT_WIDTH` - 默认视口宽度
- `DEFAULT_VIEWPORT_HEIGHT` - 默认视口高度
- `DEFAULT_USER_AGENT` - 默认 User-Agent

---

## 🚀 核心功能

### 超时配置

定义各种操作的超时时间常量。

```python
from autospider.common.constants import (
    DEFAULT_TIMEOUT_MS,
    PAGE_LOAD_TIMEOUT_MS,
    ELEMENT_WAIT_TIMEOUT_MS
)

print(f"默认超时: {DEFAULT_TIMEOUT_MS}ms")
print(f"页面加载超时: {PAGE_LOAD_TIMEOUT_MS}ms")
print(f"元素等待超时: {ELEMENT_WAIT_TIMEOUT_MS}ms")
```

### 重试配置

定义重试策略的常量。

```python
from autospider.common.constants import (
    MAX_RETRIES,
    RETRY_DELAY_MS
)

print(f"最大重试次数: {MAX_RETRIES}")
print(f"重试延迟: {RETRY_DELAY_MS}ms")
```

---

## 💡 特性说明

### 常量类型

支持多种类型的常量：

```python
# 超时时间（毫秒）
DEFAULT_TIMEOUT_MS = 30000

# 重试次数
MAX_RETRIES = 3

# 视口尺寸
DEFAULT_VIEWPORT_WIDTH = 1280
DEFAULT_VIEWPORT_HEIGHT = 720

# 字符串常量
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
```

### 常量分组

按功能分组组织常量：

```python
# 超时配置
TIMEOUT_CONFIG = {
    "default": 30000,
    "page_load": 30000,
    "element_wait": 5000
}

# 重试配置
RETRY_CONFIG = {
    "max_retries": 3,
    "retry_delay": 1000
}
```

---

## 🔧 使用示例

### 完整的常量使用流程

```python
from autospider.common.constants import (
    DEFAULT_TIMEOUT_MS,
    PAGE_LOAD_TIMEOUT_MS,
    MAX_RETRIES,
    RETRY_DELAY_MS,
    DEFAULT_VIEWPORT_WIDTH,
    DEFAULT_VIEWPORT_HEIGHT
)

# 使用超时常量
timeout = DEFAULT_TIMEOUT_MS
print(f"使用超时: {timeout}ms")

# 使用重试常量
max_retries = MAX_RETRIES
retry_delay = RETRY_DELAY_MS
print(f"重试配置: {max_retries}次，延迟{retry_delay}ms")

# 使用视口常量
viewport_width = DEFAULT_VIEWPORT_WIDTH
viewport_height = DEFAULT_VIEWPORT_HEIGHT
print(f"视口大小: {viewport_width}x{viewport_height}")
```

### 自定义常量

```python
from autospider.common.constants import DEFAULT_TIMEOUT_MS

# 基于默认常量创建自定义配置
custom_timeout = DEFAULT_TIMEOUT_MS * 2  # 双倍超时时间
print(f"自定义超时: {custom_timeout}ms")

# 基于默认常量创建视口配置
custom_width = DEFAULT_VIEWPORT_WIDTH + 400
custom_height = DEFAULT_VIEWPORT_HEIGHT + 360
print(f"自定义视口: {custom_width}x{custom_height}")
```

---

## 📝 最佳实践

### 常量定义

1. **命名规范**：使用大写字母和下划线
2. **类型明确**：明确常量的数据类型
3. **文档注释**：为每个常量添加详细注释
4. **分组组织**：按功能分组组织常量

### 常量使用

1. **避免魔法数字**：使用常量代替硬编码数字
2. **集中管理**：将常量集中在一个文件中
3. **版本控制**：使用版本控制管理常量变更
4. **文档更新**：更新常量时同步更新文档

---

## 🔍 故障排除

### 常见问题

1. **超时时间不合理**
   - 检查网络环境
   - 验证目标网站响应时间
   - 调整超时常量

2. **重试次数过多**
   - 检查网络稳定性
   - 验证目标网站可用性
   - 调整重试配置

3. **视口尺寸不合适**
   - 检查目标网站响应式设计
   - 验证页面布局
   - 调整视口尺寸

### 调试技巧

```python
# 检查常量值
from autospider.common.constants import DEFAULT_TIMEOUT_MS
print(f"默认超时: {DEFAULT_TIMEOUT_MS}ms")

# 测试超时配置
import time
start_time = time.time()
# 执行操作
end_time = time.time()
elapsed = (end_time - start_time) * 1000
print(f"实际耗时: {elapsed}ms")
```

---

## 📚 常量参考

### 超时配置

| 常量名 | 值 | 单位 | 说明 |
|---------|-----|------|------|
| DEFAULT_TIMEOUT_MS | 30000 | ms | 默认超时时间 |
| PAGE_LOAD_TIMEOUT_MS | 30000 | ms | 页面加载超时时间 |
| ELEMENT_WAIT_TIMEOUT_MS | 5000 | ms | 元素等待超时时间 |

### 重试配置

| 常量名 | 值 | 单位 | 说明 |
|---------|-----|------|------|
| MAX_RETRIES | 3 | 次 | 最大重试次数 |
| RETRY_DELAY_MS | 1000 | ms | 重试延迟时间 |

### 视口配置

| 常量名 | 值 | 单位 | 说明 |
|---------|-----|------|------|
| DEFAULT_VIEWPORT_WIDTH | 1280 | px | 默认视口宽度 |
| DEFAULT_VIEWPORT_HEIGHT | 720 | px | 默认视口高度 |

---

*最后更新: 2026-01-08*
