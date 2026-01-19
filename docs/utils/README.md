# Utils

Utils 模块包含一系列通用的工具函数，涵盖文件操作、异步 IO、模板渲染等功能，供项目中所有模块调用。

---

## 📁 模块结构

- `file_utils.py`: 同步文件操作工具（创建目录、读写 JSON 等）。
- `file_utils_async.py`: 异步文件操作工具，基于 `aiofiles`，适用于高并发场景。
- `prompt_template.py`: 通用 Prompt 模板引擎，支持 YAML 格式和 Jinja2 渲染。

---

## 🚀 核心工具

### 1. 异步文件操作 (`file_utils_async.py`)
提供非阻塞的文件系统操作：
- `ensure_directory`: 异步确保目录存在。
- `save_json_async`: 异步保存字典为 JSON 文件。
- `load_json_async`: 异步加载 JSON 文件。
- `calculate_hash_async`: 异步计算文件哈希值。

### 2. Prompt 模板引擎 (`prompt_template.py`)
统一管理 LLM 提示词：
- **YAML 存储**: 提示词按模块存储在 YAML 文件中。
- **Jinja2 渲染**: 支持复杂的循环和条件逻辑。
- **优雅降级**: 若环境无 Jinja2，自动回退到简单占位符替换。
- **高性能**: 内置 LRU 缓存，避免重复读取磁盘。

---

## 🛠️ 使用示例

### 渲染 Prompt
```python
from common.utils.prompt_template import render_template

# 加载 yaml 并渲染指定部分
prompt = render_template(
    file_path="prompts/agent.yaml",
    section="system_prompt",
    variables={"name": "Crawler"}
)
```

### 异步保存数据
```python
from common.utils.file_utils_async import save_json_async

await save_json_async("output/data.json", {"status": "success"})
```
