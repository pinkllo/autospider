# config.py - 配置管理

config.py 模块提供 AutoSpider 项目的配置管理功能，使用 Pydantic 的 BaseModel 实现类型安全的配置管理，支持环境变量覆盖。

---

## 📁 文件路径

```
src/autospider/common/config.py
```

---

## 📑 函数目录

### ⚙️ 配置类
- `LLMConfig` - LLM 配置
- `BrowserConfig` - 浏览器配置
- `AgentConfig` - Agent 配置
- `RedisConfig` - Redis 配置
- `URLCollectorConfig` - URL 收集器配置
- `Config` - 全局配置

### 🔧 配置方法
- `Config.load()` - 加载配置
- `Config.ensure_dirs()` - 确保输出目录存在

---

## 🚀 核心功能

### LLMConfig

LLM 配置类，管理大语言模型的连接和参数配置。

```python
from autospider.common.config import LLMConfig

llm_config = LLMConfig(
    api_key="your-api-key",
    api_base="https://api.siliconflow.cn/v1",
    model="Qwen3-VL-235B-A22B-Instruct",
    planner_model="Qwen3-VL-235B-A22B-Instruct",
    temperature=0.1,
    max_tokens=8192
)

print(f"API Key: {llm_config.api_key}")
print(f"模型: {llm_config.model}")
```

### BrowserConfig

浏览器配置类，管理浏览器实例的参数。

```python
from autospider.common.config import BrowserConfig

browser_config = BrowserConfig(
    headless=True,
    viewport_width=1280,
    viewport_height=720,
    slow_mo=0,
    timeout_ms=30000
)

print(f"无头模式: {browser_config.headless}")
print(f"视口大小: {browser_config.viewport_width}x{browser_config.viewport_height}")
```

### Config

全局配置类，聚合所有配置项。

```python
from autospider.common.config import config

# 使用全局配置实例
print(f"LLM 模型: {config.llm.model}")
print(f"浏览器视口: {config.browser.viewport_width}x{config.browser.viewport_height}")
print(f"Redis 启用: {config.redis.enabled}")

# 确保输出目录存在
config.ensure_dirs()
```

---

## 💡 特性说明

### 环境变量支持

所有配置项都支持通过环境变量进行覆盖：

```bash
# .env 文件
AIPING_API_KEY=your-api-key
AIPING_MODEL=gpt-4-vision
HEADLESS=true
VIEWPORT_WIDTH=1920
VIEWPORT_HEIGHT=1080
REDIS_ENABLED=true
REDIS_HOST=localhost
REDIS_PORT=6379
```

### 类型安全

使用 Pydantic 进行类型验证，确保配置和数据的正确性：

```python
from pydantic import ValidationError

try:
    config = LLMConfig(
        api_key="test-key",
        model="gpt-4",
        temperature=0.1,
        max_tokens=8192
    )
except ValidationError as e:
    print(f"配置验证失败: {e}")
```

### 默认值

所有配置项都有合理的默认值：

```python
# LLM 配置默认值
- api_key: 从环境变量 AIPING_API_KEY 读取，默认为空字符串
- api_base: 从环境变量 AIPING_API_BASE 读取，默认为 "https://api.siliconflow.cn/v1"
- model: 从环境变量 AIPING_MODEL 读取，默认为 "Qwen3-VL-235B-A22B-Instruct"
- temperature: 默认 0.1
- max_tokens: 默认 8192

# 浏览器配置默认值
- headless: 从环境变量 HEADLESS 读取，默认为 False
- viewport_width: 从环境变量 VIEWPORT_WIDTH 读取，默认为 1280
- viewport_height: 从环境变量 VIEWPORT_HEIGHT 读取，默认为 720
- slow_mo: 从环境变量 SLOW_MO 读取，默认为 0
- timeout_ms: 从环境变量 STEP_TIMEOUT_MS 读取，默认为 30000
```

---

## 🔧 使用示例

### 完整的配置管理流程

```python
from autospider.common.config import config

# 方式 1: 使用全局配置
print(f"LLM API Key: {config.llm.api_key}")
print(f"LLM 模型: {config.llm.model}")
print(f"浏览器无头模式: {config.browser.headless}")

# 方式 2: 创建自定义配置
from autospider.common.config import Config, LLMConfig, BrowserConfig

custom_config = Config(
    llm=LLMConfig(
        api_key="custom-key",
        model="gpt-4",
        temperature=0.2
    ),
    browser=BrowserConfig(
        headless=True,
        viewport_width=1920,
        viewport_height=1080
    )
)

# 确保输出目录存在
config.ensure_dirs()
```

### 环境变量配置

```python
import os
from autospider.common.config import config

# 设置环境变量
os.environ["AIPING_API_KEY"] = "new-api-key"
os.environ["HEADLESS"] = "true"

# 重新加载配置
from autospider.common.config import Config
new_config = Config.load()

print(f"新的 API Key: {new_config.llm.api_key}")
print(f"新的无头模式: {new_config.browser.headless}")
```

---

## 📝 最佳实践

### 配置管理

1. **环境变量优先**：使用环境变量覆盖默认配置
2. **类型验证**：利用 Pydantic 的类型验证功能
3. **目录管理**：使用 `ensure_dirs()` 确保输出目录存在
4. **配置分离**：不同环境使用不同的配置文件

### 安全性

1. **敏感信息**：不要在代码中硬编码 API Key
2. **环境变量**：使用环境变量存储敏感信息
3. **.env 文件**：将 .env 文件添加到 .gitignore
4. **默认值**：为所有配置项提供安全的默认值

### 配置验证

1. **启动检查**：在应用启动时验证配置完整性
2. **错误处理**：捕获并处理配置验证错误
3. **日志记录**：记录配置加载过程
4. **文档说明**：为每个配置项添加详细的文档字符串

---

## 🔍 故障排除

### 常见问题

1. **配置加载失败**
   - 检查 .env 文件是否存在
   - 验证环境变量格式
   - 确认默认值是否合理

2. **类型验证失败**
   - 检查环境变量类型是否正确
   - 验证数值范围是否在有效范围内
   - 确认布尔值格式（true/false）

3. **目录创建失败**
   - 检查文件系统权限
   - 验证磁盘空间是否充足
   - 确认路径是否有效

### 调试技巧

```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 检查配置
print(f"配置内容: {config.model_dump_json(indent=2)}")

# 验证环境变量
import os
print(f"AIPING_API_KEY: {os.getenv('AIPING_API_KEY')}")
print(f"HEADLESS: {os.getenv('HEADLESS')}")
```

---

## 📚 配置项参考

### LLMConfig 配置项

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|-----------|--------|------|
| api_key | AIPING_API_KEY | "" | LLM API 密钥 |
| api_base | AIPING_API_BASE | "https://api.siliconflow.cn/v1" | LLM API 基础 URL |
| model | AIPING_MODEL | "Qwen3-VL-235B-A22B-Instruct" | 主模型名称 |
| planner_model | SILICON_PLANNER_MODEL | None | Planner 专用模型 |
| planner_api_key | SILICON_PLANNER_API_KEY | None | Planner API 密钥 |
| planner_api_base | SILICON_PLANNER_API_BASE | None | Planner API 基础 URL |
| temperature | - | 0.1 | 温度参数 |
| max_tokens | - | 8192 | 最大 Token 数 |

### BrowserConfig 配置项

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|-----------|--------|------|
| headless | HEADLESS | false | 是否无头模式 |
| viewport_width | VIEWPORT_WIDTH | 1280 | 视口宽度 |
| viewport_height | VIEWPORT_HEIGHT | 720 | 视口高度 |
| slow_mo | SLOW_MO | 0 | 慢动作延迟（毫秒） |
| timeout_ms | STEP_TIMEOUT_MS | 30000 | 超时时间（毫秒） |

### RedisConfig 配置项

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|-----------|--------|------|
| enabled | REDIS_ENABLED | false | 是否启用 Redis |
| host | REDIS_HOST | localhost | Redis 服务器地址 |
| port | REDIS_PORT | 6379 | Redis 端口 |
| password | REDIS_PASSWORD | None | Redis 密码 |
| db | REDIS_DB | 0 | Redis 数据库索引 |
| key_prefix | REDIS_KEY_PREFIX | "autospider:urls" | 键前缀 |

### URLCollectorConfig 配置项

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|-----------|--------|------|
| explore_count | EXPLORE_COUNT | 3 | 探索阶段进入的详情页数量 |
| max_scrolls | MAX_SCROLLS | 5 | 最大滚动次数（单页） |
| no_new_url_threshold | NO_NEW_URL_THRESHOLD | 2 | 连续无新 URL 的滚动次数后停止 |
| target_url_count | TARGET_URL_COUNT | 400 | 目标 URL 数量 |
| max_pages | MAX_PAGES | 40 | 最大翻页次数 |
| action_delay_base | ACTION_DELAY_BASE | 1.0 | 页面操作基础延迟（秒） |
| action_delay_random | ACTION_DELAY_RANDOM | 0.5 | 页面操作延迟随机波动范围（秒） |
| page_load_delay | PAGE_LOAD_DELAY | 1.5 | 页面加载等待时间（秒） |
| scroll_delay | SCROLL_DELAY | 0.5 | 滚动操作延迟（秒） |
| debug_delay | DEBUG_DELAY | true | 调试：打印延迟信息 |
| validate_mark_id | VALIDATE_MARK_ID | true | 是否启用 mark_id 与文本的验证 |
| mark_id_match_threshold | MARK_ID_MATCH_THRESHOLD | 0.6 | 文本匹配相似度阈值 |
| debug_mark_id_validation | DEBUG_MARK_ID_VALIDATION | true | 调试：打印验证信息 |
| max_validation_retries | MAX_VALIDATION_RETRIES | 1 | 验证失败后的最大重试次数 |
| backoff_factor | BACKOFF_FACTOR | 1.5 | 退避因子（遭遇反爬时延迟倍增因子） |
| max_backoff_level | MAX_BACKOFF_LEVEL | 3 | 最大降速等级 |
| credit_recovery_pages | CREDIT_RECOVERY_PAGES | 5 | 连续成功多少页后恢复一级 |

---

*最后更新: 2026-01-08*
