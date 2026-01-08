# Utils 模块

Utils 模块提供 AutoSpider 项目的通用工具函数和辅助类，包括 Prompt 模板渲染、日志记录、文件操作、时间处理等功能。

---

## 📁 模块结构

```
src/autospider/utils/
├── __init__.py              # 模块导出
├── prompt_template.py       # Prompt 模板渲染工具
├── logger.py               # 日志记录工具
├── file_utils.py           # 文件操作工具
├── time_utils.py           # 时间处理工具
└── string_utils.py         # 字符串处理工具
```

---

## 📑 函数目录

### 📝 Prompt 模板渲染 (prompt_template.py)
- `render_template(file_path, section=None, variables=None)` - 加载 YAML 模板并渲染指定部分
- `render_text(text, variables=None)` - 渲染一段独立的文本字符串
- `is_jinja2_available()` - 检查是否支持 Jinja2
- `load_template_file(file_path)` - 加载并缓存 YAML 文件
- `clear_template_cache()` - 清除文件缓存
- `get_template_sections(file_path)` - 获取模板文件中的所有 Section

### 📊 日志记录 (logger.py)
- `get_logger(name)` - 获取日志记录器
- `setup_logging(level, log_file)` - 设置日志配置
- `log_function_call(func)` - 函数调用日志装饰器

### 📁 文件操作 (file_utils.py)
- `read_file(file_path)` - 读取文件内容
- `write_file(file_path, content)` - 写入文件内容
- `append_file(file_path, content)` - 追加文件内容
- `delete_file(file_path)` - 删除文件
- `ensure_dir(dir_path)` - 确保目录存在
- `get_file_hash(file_path)` - 获取文件哈希值

### ⏰ 时间处理 (time_utils.py)
- `get_current_timestamp()` - 获取当前时间戳
- `format_timestamp(timestamp, format)` - 格式化时间戳
- `parse_datetime(date_string)` - 解析日期字符串
- `sleep(seconds)` - 异步睡眠
- `retry_with_delay(func, max_retries, delay)` - 带延迟的重试

### 🔤 字符串处理 (string_utils.py)
- `truncate_string(text, max_length)` - 截断字符串
- `normalize_whitespace(text)` - 规范化空白字符
- `extract_urls(text)` - 提取文本中的 URL
- `extract_emails(text)` - 提取文本中的邮箱
- `clean_text(text)` - 清理文本内容

---

## 🚀 核心功能

### Prompt 模板渲染

Prompt 模板渲染工具提供统一的 Prompt 管理和渲染功能，支持 Jinja2 模板语法。

```python
from autospider.utils.prompt_template import render_template, render_text

# 渲染 YAML 模板
prompt = render_template(
    "prompts/agent/agent.yaml",
    section="user_prompt",
    variables={"task": "点击登录按钮"}
)

# 渲染文本模板
text = render_text(
    "Hello {{name}}!",
    variables={"name": "World"}
)

print(f"渲染后的文本: {text}")
```

### 日志记录

日志记录工具提供统一的日志管理功能，支持多种日志级别和输出格式。

```python
from autospider.utils.logger import get_logger, setup_logging

# 设置日志配置
setup_logging(level="DEBUG", log_file="app.log")

# 获取日志记录器
logger = get_logger(__name__)

# 记录日志
logger.debug("调试信息")
logger.info("普通信息")
logger.warning("警告信息")
logger.error("错误信息")
logger.critical("严重错误")
```

### 文件操作

文件操作工具提供便捷的文件读写和管理功能。

```python
from autospider.utils.file_utils import (
    read_file,
    write_file,
    append_file,
    ensure_dir
)

# 读取文件
content = read_file("config.yaml")

# 写入文件
write_file("output.txt", "Hello, World!")

# 追加文件
append_file("output.txt", "\nNew line")

# 确保目录存在
ensure_dir("output/data")
```

### 时间处理

时间处理工具提供便捷的时间格式化和转换功能。

```python
from autospider.utils.time_utils import (
    get_current_timestamp,
    format_timestamp,
    parse_datetime
)

# 获取当前时间戳
timestamp = get_current_timestamp()

# 格式化时间戳
formatted = format_timestamp(timestamp, "%Y-%m-%d %H:%M:%S")

# 解析日期字符串
dt = parse_datetime("2026-01-08 10:00:00")

print(f"当前时间: {formatted}")
print(f"解析结果: {dt}")
```

---

## 💡 特性说明

### Jinja2 优先与优雅降级

Prompt 模板渲染支持 Jinja2 模板引擎，如果未安装则自动降级到简单的字符串替换：

```python
# 检查 Jinja2 是否可用
from autospider.utils.prompt_template import is_jinja2_available

if is_jinja2_available():
    print("Jinja2 可用，支持高级模板语法")
else:
    print("Jinja2 不可用，使用简单字符串替换")
```

### 模板缓存

模板文件使用 LRU 缓存，提高重复加载的性能：

```python
from autospider.utils.prompt_template import clear_template_cache

# 清除模板缓存
clear_template_cache()

# 再次加载将读取最新内容
prompt = render_template("prompts/agent/agent.yaml")
```

### 日志装饰器

提供函数调用日志装饰器，自动记录函数调用信息：

```python
from autospider.utils.logger import log_function_call

@log_function_call
def process_data(data):
    """处理数据"""
    return data.upper()

# 调用函数会自动记录日志
result = process_data("hello")
```

---

## 🔧 使用示例

### 完整的 Prompt 渲染流程

```python
import asyncio
from autospider.utils.prompt_template import (
    render_template,
    get_template_sections
)

async def render_prompts():
    """渲染 Prompt 模板"""

    # 获取模板文件中的所有 Section
    sections = get_template_sections("prompts/agent/agent.yaml")
    print(f"可用的 Section: {sections}")

    # 渲染系统 Prompt
    system_prompt = render_template(
        "prompts/agent/agent.yaml",
        section="system_prompt",
        variables={}
    )

    # 渲染用户 Prompt
    user_prompt = render_template(
        "prompts/agent/agent.yaml",
        section="user_prompt",
        variables={
            "task": "点击登录按钮",
            "marks": [
                {"mark_id": 5, "tag": "button", "text": "登录"}
            ]
        }
    )

    print(f"系统 Prompt: {system_prompt}")
    print(f"用户 Prompt: {user_prompt}")

# 使用示例
asyncio.run(render_prompts())
```

### 日志记录示例

```python
import asyncio
from autospider.utils.logger import get_logger, setup_logging

async def log_example():
    """日志记录示例"""

    # 设置日志配置
    setup_logging(level="DEBUG", log_file="app.log")

    # 获取日志记录器
    logger = get_logger(__name__)

    try:
        logger.info("开始处理任务")

        # 模拟处理过程
        for i in range(5):
            logger.debug(f"处理第 {i+1} 项")
            await asyncio.sleep(0.1)

        logger.info("任务处理完成")

    except Exception as e:
        logger.error(f"任务处理失败: {e}")
        raise

# 使用示例
asyncio.run(log_example())
```

### 文件操作示例

```python
import asyncio
from autospider.utils.file_utils import (
    read_file,
    write_file,
    ensure_dir,
    get_file_hash
)

async def file_operations():
    """文件操作示例"""

    # 确保目录存在
    ensure_dir("output/data")

    # 写入文件
    content = "Hello, World!\nThis is a test file."
    write_file("output/data/test.txt", content)

    # 读取文件
    read_content = read_file("output/data/test.txt")
    print(f"读取的内容: {read_content}")

    # 获取文件哈希
    file_hash = get_file_hash("output/data/test.txt")
    print(f"文件哈希: {file_hash}")

# 使用示例
asyncio.run(file_operations())
```

---

## 📝 最佳实践

### Prompt 模板管理

1. **模块化**：按功能模块组织 Prompt 文件
2. **命名规范**：使用清晰的文件命名
3. **变量一致性**：使用一致的变量命名
4. **缓存管理**：定期清除模板缓存

### 日志记录

1. **日志级别**：合理设置日志级别
2. **日志格式**：使用统一的日志格式
3. **日志文件**：定期轮转日志文件
4. **性能考虑**：避免过度日志记录

### 文件操作

1. **异常处理**：妥善处理文件操作异常
2. **路径处理**：使用绝对路径避免路径问题
3. **编码处理**：明确指定文件编码
4. **资源管理**：及时关闭文件句柄

### 时间处理

1. **时区处理**：注意时区转换问题
2. **格式统一**：使用统一的时间格式
3. **精度控制**：根据需要选择时间精度
4. **性能考虑**：避免频繁的时间转换

---

## 🔍 故障排除

### 常见问题

1. **Prompt 渲染失败**
   - 检查模板文件路径是否正确
   - 验证 YAML 格式是否正确
   - 确认变量是否完整

2. **日志记录失败**
   - 检查日志文件路径是否可写
   - 验证日志配置是否正确
   - 确认日志级别设置是否合理

3. **文件操作失败**
   - 检查文件路径是否正确
   - 验证文件权限是否足够
   - 确认文件编码是否正确

### 调试技巧

```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 检查模板文件
from autospider.utils.prompt_template import get_template_sections
sections = get_template_sections("prompts/agent/agent.yaml")
print(f"可用的 Section: {sections}")

# 检查文件内容
from autospider.utils.file_utils import read_file
content = read_file("config.yaml")
print(f"文件内容: {content}")

# 检查时间戳
from autospider.utils.time_utils import get_current_timestamp, format_timestamp
timestamp = get_current_timestamp()
formatted = format_timestamp(timestamp, "%Y-%m-%d %H:%M:%S")
print(f"当前时间: {formatted}")
```

---

## 📚 工具函数参考

### Prompt 模板渲染

```python
# 渲染 YAML 模板
render_template(
    file_path="prompts/agent/agent.yaml",
    section="user_prompt",
    variables={"task": "点击登录按钮"}
)

# 渲染文本模板
render_text(
    "Hello {{name}}!",
    variables={"name": "World"}
)

# 获取模板 Section
get_template_sections("prompts/agent/agent.yaml")

# 清除模板缓存
clear_template_cache()
```

### 日志记录

```python
# 设置日志配置
setup_logging(level="DEBUG", log_file="app.log")

# 获取日志记录器
logger = get_logger(__name__)

# 记录日志
logger.debug("调试信息")
logger.info("普通信息")
logger.warning("警告信息")
logger.error("错误信息")
logger.critical("严重错误")
```

### 文件操作

```python
# 读取文件
read_file("config.yaml")

# 写入文件
write_file("output.txt", "Hello, World!")

# 追加文件
append_file("output.txt", "\nNew line")

# 删除文件
delete_file("output.txt")

# 确保目录存在
ensure_dir("output/data")

# 获取文件哈希
get_file_hash("output.txt")
```

### 时间处理

```python
# 获取当前时间戳
get_current_timestamp()

# 格式化时间戳
format_timestamp(timestamp, "%Y-%m-%d %H:%M:%S")

# 解析日期字符串
parse_datetime("2026-01-08 10:00:00")

# 异步睡眠
await sleep(1.0)

# 带延迟的重试
retry_with_delay(func, max_retries=3, delay=1.0)
```

---

*最后更新: 2026-01-08*
