# logger.py - 日志记录

logger.py 模块提供统一的日志记录功能，支持多种日志级别和输出格式。

---

## 📁 文件路径

```
src/autospider/common/logger.py
```

---

## 📑 函数目录

### 📊 日志记录
- `get_logger(name)` - 获取日志记录器
- `setup_logging(level, log_file)` - 设置日志配置

---

## 🚀 核心功能

### get_logger

获取指定名称的日志记录器实例。

```python
from autospider.common.logger import get_logger

# 获取日志记录器
logger = get_logger(__name__)

# 记录日志
logger.debug("调试信息")
logger.info("普通信息")
logger.warning("警告信息")
logger.error("错误信息")
logger.critical("严重错误")
```

### setup_logging

设置全局日志配置，包括日志级别和输出文件。

```python
from autospider.common.logger import setup_logging

# 设置日志配置
setup_logging(
    level="DEBUG",
    log_file="app.log"
)

# 配置后所有日志记录器都将使用这个配置
logger = get_logger(__name__)
logger.info("日志系统已配置")
```

---

## 💡 特性说明

### 日志级别

支持标准的 Python 日志级别：

```python
# DEBUG: 详细的调试信息
logger.debug("调试信息")

# INFO: 一般的信息
logger.info("普通信息")

# WARNING: 警告信息
logger.warning("警告信息")

# ERROR: 错误信息
logger.error("错误信息")

# CRITICAL: 严重错误
logger.critical("严重错误")
```

### 日志格式

日志格式包含时间戳、日志级别、模块名称和消息：

```python
# 日志格式示例
2026-01-08 10:00:00,123 - DEBUG - autospider.common.logger - 调试信息
2026-01-08 10:00:00,456 - INFO - autospider.common.logger - 普通信息
2026-01-08 10:00:01,789 - WARNING - autospider.common.logger - 警告信息
```

### 文件输出

支持将日志输出到文件：

```python
# 配置文件输出
setup_logging(
    level="DEBUG",
    log_file="app.log"
)

# 日志将同时输出到控制台和文件
logger.info("这条日志会输出到控制台和文件")
```

---

## 🔧 使用示例

### 完整的日志记录流程

```python
from autospider.common.logger import get_logger, setup_logging

# 设置日志配置
setup_logging(level="DEBUG", log_file="app.log")

# 获取日志记录器
logger = get_logger(__name__)

try:
    logger.info("开始处理任务")

    # 模拟处理过程
    for i in range(5):
        logger.debug(f"处理第 {i+1} 项")

    logger.info("任务处理完成")

except Exception as e:
    logger.error(f"任务处理失败: {e}")
    raise
```

### 不同模块的日志记录

```python
from autospider.common.logger import get_logger

# 不同模块使用不同的日志记录器
main_logger = get_logger("autospider.main")
browser_logger = get_logger("autospider.browser")
collector_logger = get_logger("autospider.collector")

# 每个模块的日志会包含模块名称
main_logger.info("主模块日志")
browser_logger.info("浏览器模块日志")
collector_logger.info("收集器模块日志")
```

---

## 📝 最佳实践

### 日志记录

1. **日志级别**：合理设置日志级别
2. **日志格式**：使用统一的日志格式
3. **日志文件**：定期轮转日志文件
4. **性能考虑**：避免过度日志记录

### 日志内容

1. **有意义的信息**：记录有意义的日志信息
2. **上下文信息**：包含足够的上下文信息
3. **错误详情**：记录详细的错误信息和堆栈
4. **性能指标**：记录关键的性能指标

### 日志配置

1. **环境变量**：使用环境变量配置日志级别
2. **开发环境**：开发环境使用 DEBUG 级别
3. **生产环境**：生产环境使用 INFO 或 WARNING 级别
4. **日志轮转**：配置日志文件轮转策略

---

## 🔍 故障排除

### 常见问题

1. **日志文件写入失败**
   - 检查文件路径是否可写
   - 验证文件权限是否足够
   - 确认磁盘空间是否充足

2. **日志级别不生效**
   - 检查日志配置是否正确
   - 验证日志记录器是否正确获取
   - 确认日志级别设置是否合理

3. **日志格式不正确**
   - 检查日志格式字符串是否正确
   - 验证时间格式是否有效
   - 确认模块名称是否正确

### 调试技巧

```python
# 检查日志配置
import logging
root_logger = logging.getLogger()
print(f"根日志记录器级别: {root_logger.level}")
print(f"根日志记录器处理器: {root_logger.handlers}")

# 检查特定日志记录器
module_logger = logging.getLogger("autospider.common")
print(f"模块日志记录器级别: {module_logger.level}")
print(f"模块日志记录器处理器: {module_logger.handlers}")
```

---

## 📚 日志级别参考

| 日志级别 | 数值 | 使用场景 | 示例 |
|---------|------|---------|------|
| DEBUG | 10 | 详细的调试信息 | 变量值、函数调用 |
| INFO | 20 | 一般的信息 | 任务开始、完成 |
| WARNING | 30 | 警告信息 | 降级、重试 |
| ERROR | 40 | 错误信息 | 异常、失败 |
| CRITICAL | 50 | 严重错误 | 系统崩溃、致命错误 |

---

*最后更新: 2026-01-08*
