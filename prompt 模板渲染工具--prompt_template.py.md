# Prompt Template
本文档介绍 `src/common/utils/prompt_template.py` 模块的使用方法。该模块提供了一个通用的 Prompt 模板引擎，支持 Jinja2 渲染及优雅降级。

## 配合使用（推荐）
+ 每个模块创建自己的prompt文件夹，用于存放自己代码中用到的prompt
+ 一个 py文件 中用到的prompt 都放在同一个 yaml 文件（与py文件同名）中
+ 案例：<!-- 这是一张图片，ocr 内容为： -->
![](https://cdn.nlark.com/yuque/0/2026/png/34714600/1767684285412-d323efa7-11b1-4e31-a8a4-76c7e241964f.png)

---

## 📑 函数目录
### 🚀 核心功能
+ `render_template(file_path, section=None, variables=None)` - 加载 YAML 模板并渲染指定部分（最常用）
+ `render_text(text, variables=None)` - 渲染一段独立的文本字符串

### ⚙️ 环境与缓存
+ `is_jinja2_available()` - 检查是否支持 Jinja2
+ `load_template_file(file_path)` - 加载并缓存 YAML 文件
+ `clear_template_cache()` - 清除文件缓存
+ `get_template_sections(file_path)` - 获取模板文件中的所有 Section

---

## 📦 安装依赖
```bash
uv add Jinja2
```

---

## 📦 导入方式
```python
from common.utils.prompt_template import (
    render_template,
    render_text,
    get_template_sections
)

# 或者导入整个模块
from common.utils import prompt_template
```

---

## 🚀 核心功能
### `render_template(file_path, section=None, variables=None)`
加载 YAML 模板文件并渲染指定部分。这是最核心的接口，一步完成「加载 -> 提取 -> 渲染」流程。

**参数：**

+ `file_path` (str): YAML 模板文件的完整路径（建议使用绝对路径）。
+ `section` (str | None): 要渲染的 YAML 一级 Key（如 `system_prompt`, `user_prompt`）。
    - 若指定了 `section`，则提取该 Key 对应的内容进行渲染。
    - 若为 `None`，则将整个 YAML 内容序列化为字符串并渲染。
+ `variables` (dict | None): 变量字典，用于替换模板中的占位符。

**返回：**

+ `str`: 渲染后的 Prompt 文本。

**示例：**

```python
# 示例 1：渲染特定 Section
prompt = render_template(
    "prompts/extract.yaml",
    section="user_prompt",
    variables={"content": "页面内容..."}
)

# 示例 2：渲染整个文件
full_config = render_template(
    "configs/agent_config.yaml",
    variables={"env": "prod"}
)
```

### `render_text(text, variables=None)`
渲染一段独立的模板文本。

**参数：**

+ `text` (str): 包含占位符（如 `{{name}}`）的原始文本。
+ `variables` (dict | None): 变量字典。

**返回：**

+ `str`: 渲染后的文本。

**示例：**

```python
msg = render_text(
    "Hello {{name}}!",
    variables={"name": "World"}
)
# 输出: "Hello World!"
```

---

## ⚙️ 环境与缓存
### `load_template_file(file_path)`
加载并缓存 YAML 模板文件。使用 LRU 缓存，同一文件路径只会被读取一次，显著提升高频调用场景性能。

**参数：**

+ `file_path` (str): YAML 文件路径。

**返回：**

+ `dict`: 解析后的字典数据。

### `clear_template_cache()`
清除模板文件的 LRU 缓存。适用于开发调试场景，当模板文件内容更新后需调用此函数使更改生效。

**示例：**

```python
# 修改了 yaml 文件后...
prompt_template.clear_template_cache()
# 再次渲染将读取最新内容
```

### `get_template_sections(file_path)`
获取模板文件中所有可用的 Section 名称（一级 Key 列表）。

**参数：**

+ `file_path` (str): YAML 文件路径。

**返回：**

+ `list[str]`: Section 名称列表。

**示例：**

```python
sections = get_template_sections("prompts/role.yaml")
print(sections) 
# 输出: ['system_prompt', 'user_prompt', 'examples']
```

### `is_jinja2_available()`
检查当前环境是否安装并支持 Jinja2 模板引擎。

**返回：**

+ `bool`: 若可用返回 `True`，否则返回 `False`。

---

## 💡 特性说明
### Jinja2 优先与优雅降级
1. **Jinja2 模式**：如果环境中安装了 `jinja2` 库，本模块将使用 Jinja2 引擎进行渲染。这意味着你可以使用完整的高级语法：
    - 循环：`{% for item in items %}...{% endfor %}`
    - 条件：`{% if is_debug %}...{% endif %}`
    - 过滤器：`{{ value | upper }}`
2. **降级模式**：如果未安装 `jinja2`，模块会自动回退到简单的字符串替换模式。
    - 仅支持 `{{key}}` 形式的变量替换。
    - 不支持复杂的逻辑控制。

**注意**：为了保证 Prompt 的通用性，建议优先编写兼容两种模式的简单模板，或者明确项目依赖 `jinja2`。

