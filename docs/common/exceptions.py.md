# exceptions.py - 异常定义

exceptions.py 模块定义 AutoSpider 项目使用的自定义异常类，用于处理各种错误情况。

---

## 📁 文件路径

```
src/autospider/common/exceptions.py
```

---

## 📑 异常目录

### 🔧 系统异常
- `AutoSpiderException` - 基础异常类
- `ConfigError` - 配置错误
- `BrowserError` - 浏览器错误

### 🔄 爬取异常
- `CrawlerError` - 爬取错误
- `URLCollectorError` - URL 收集错误
- `ExtractionError` - 数据提取错误

### 🤖️ 浏览器异常
- `NavigationError` - 导航错误
- `ElementNotFoundError` - 元素未找到错误
- `TimeoutError` - 超时错误

### 🤖️ LLM 异常
- `LLMError` - LLM 调用错误
- `PromptError` - Prompt 渲染错误
- `ResponseError` - 响应解析错误

---

## 🚀 核心功能

### AutoSpiderException

基础异常类，所有自定义异常的父类。

```python
from autospider.common.exceptions import AutoSpiderException

# 抛出基础异常
raise AutoSpiderException("基础异常消息")
```

### ConfigError

配置错误，用于处理配置相关的问题。

```python
from autospider.common.exceptions import ConfigError

# 抛出配置错误
raise ConfigError("配置文件格式错误")
raise ConfigError("缺少必需的配置项")
```

### BrowserError

浏览器错误，用于处理浏览器相关的问题。

```python
from autospider.common.exceptions import BrowserError

# 抛出浏览器错误
raise BrowserError("浏览器启动失败")
raise BrowserError("页面加载超时")
```

### CrawlerError

爬取错误，用于处理爬取过程中的问题。

```python
from autospider.common.exceptions import CrawlerError

# 抛出爬取错误
raise CrawlerError("URL 收集失败")
raise CrawlerError("数据提取失败")
```

---

## 💡 特性说明

### 异常层次结构

所有自定义异常都继承自基础异常类：

```python
# 异常层次结构
AutoSpiderException (基础异常)
├── ConfigError (配置错误)
├── BrowserError (浏览器错误)
├── CrawlerError (爬取错误)
├── NavigationError (导航错误)
├── ElementNotFoundError (元素未找到)
├── TimeoutError (超时错误)
├── LLMError (LLM 错误)
├── PromptError (Prompt 错误)
└── ResponseError (响应错误)
```

### 异常信息

每个异常都包含详细的错误信息：

```python
from autospider.common.exceptions import BrowserError

try:
    # 浏览器操作
    pass
except Exception as e:
    # 抛出详细的错误信息
    raise BrowserError(
        f"浏览器操作失败: {str(e)}",
        original_exception=e
    )
```

---

## 🔧 使用示例

### 完整的异常处理流程

```python
from autospider.common.exceptions import (
    AutoSpiderException,
    ConfigError,
    BrowserError,
    CrawlerError,
    ElementNotFoundError,
    TimeoutError
)

try:
    # 配置加载
    if not config_file.exists():
        raise ConfigError("配置文件不存在")

    # 浏览器操作
    if not browser.is_connected():
        raise BrowserError("浏览器未连接")

    # 元素操作
    if not element:
        raise ElementNotFoundError("元素未找到")

    # 超时处理
    if elapsed_time > timeout:
        raise TimeoutError(f"操作超时: {elapsed_time}ms")

except ConfigError as e:
    print(f"配置错误: {e}")
except BrowserError as e:
    print(f"浏览器错误: {e}")
except ElementNotFoundError as e:
    print(f"元素错误: {e}")
except TimeoutError as e:
    print(f"超时错误: {e}")
except AutoSpiderException as e:
    print(f"未知错误: {e}")
```

### 自定义异常

```python
from autospider.common.exceptions import AutoSpiderException

# 创建自定义异常
class CustomError(AutoSpiderException):
    """自定义异常类"""
    pass

# 使用自定义异常
try:
    # 执行操作
    pass
except Exception as e:
    raise CustomError(f"自定义错误: {str(e)}")
```

---

## 📝 最佳实践

### 异常定义

1. **继承基础异常**：所有自定义异常继承自基础异常类
2. **详细错误信息**：提供清晰的错误描述
3. **异常分类**：按功能模块分类异常
4. **错误代码**：为异常添加错误代码

### 异常处理

1. **特定异常**：捕获特定的异常类型
2. **异常链**：保留原始异常信息
3. **日志记录**：记录异常详细信息
4. **用户友好**：提供用户友好的错误提示

### 异常恢复

1. **重试机制**：对于可恢复的异常实现重试
2. **降级策略**：对于无法恢复的异常实现降级
3. **状态清理**：异常时清理资源
4. **错误报告**：收集和报告错误信息

---

## 🔍 故障排除

### 常见问题

1. **异常未被捕获**
   - 检查异常类型是否正确
   - 验证异常处理逻辑是否完整
   - 确认异常传播路径

2. **异常信息不清晰**
   - 检查异常消息是否详细
   - 验证错误代码是否正确
   - 确认上下文信息是否完整

3. **异常恢复失败**
   - 检查重试逻辑是否正确
   - 验证降级策略是否合理
   - 确认资源清理是否完整

### 调试技巧

```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 捕获并记录异常
try:
    # 执行操作
    pass
except AutoSpiderException as e:
    logging.error(f"捕获异常: {e}", exc_info=True)
    raise
```

---

## 📚 异常参考

### 系统异常

| 异常类 | 说明 | 使用场景 |
|---------|------|---------|
| AutoSpiderException | 基础异常 | 所有自定义异常的父类 |
| ConfigError | 配置错误 | 配置加载、验证失败 |
| BrowserError | 浏览器错误 | 浏览器启动、操作失败 |

### 爬取异常

| 异常类 | 说明 | 使用场景 |
|---------|------|---------|
| CrawlerError | 爬取错误 | URL 收集、数据提取失败 |
| URLCollectorError | URL 收集错误 | URL 发现、收集失败 |
| ExtractionError | 数据提取错误 | 字段提取、解析失败 |

### 浏览器异常

| 异常类 | 说明 | 使用场景 |
|---------|------|---------|
| NavigationError | 导航错误 | 页面导航失败 |
| ElementNotFoundError | 元素未找到 | 元素定位失败 |
| TimeoutError | 超时错误 | 操作超时 |

### LLM 异常

| 异常类 | 说明 | 使用场景 |
|---------|------|---------|
| LLMError | LLM 错误 | LLM 调用失败 |
| PromptError | Prompt 错误 | Prompt 渲染失败 |
| ResponseError | 响应错误 | 响应解析失败 |

---

*最后更新: 2026-01-08*
