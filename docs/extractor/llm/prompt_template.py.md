# prompt_template.py - Prompt 模板引擎

prompt_template.py 模块提供通用的 Prompt 模板引擎，支持 Jinja2 渲染及优雅降级。

---

## 📁 文件路径

```
src/autospider/extractor/llm/prompt_template.py
```

---

## 📑 函数目录

### 🚀 核心功能
- `render_template(file_path, section=None, variables=None)` - 加载 YAML 模板并渲染指定部分（最常用）
- `render_text(text, variables=None)` - 渲染一段独立的文本字符串

### ⚙️ 环境与缓存
- `is_jinja2_available()` - 检查是否支持 Jinja2
- `load_template_file(file_path)` - 加载并缓存 YAML 文件
- `clear_template_cache()` - 清除文件缓存
- `get_template_sections(file_path)` - 获取模板文件中的所有 Section

---

## 🚀 核心功能

### render_template

加载 YAML 模板文件并渲染指定部分。这是最核心的接口，一步完成「加载 -> 提取 -> 渲染」流程。

```python
from autospider.extractor.llm.prompt_template import render_template

# 示例 1：渲染特定 Section
prompt = render_template(
    "prompts/decider.yaml",
    section="system_prompt",
    variables={"task": "收集商品信息"}
)

# 示例 2：渲染整个文件
full_config = render_template(
    "prompts/planner.yaml",
    variables={"start_url": "https://example.com"}
)
```

### render_text

渲染一段独立的模板文本。

```python
from autospider.extractor.llm.prompt_template import render_text

msg = render_text(
    "Hello {{name}}!",
    variables={"name": "World"}
)
# 输出: "Hello World!"
```

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

### LRU 缓存机制

使用 LRU 缓存，同一文件路径只会被读取一次，显著提升高频调用场景性能。

```python
@lru_cache(maxsize=64)
def load_template_file(file_path: str) -> dict[str, Any]:
    """
    加载并缓存 YAML 模板文件。

    使用 LRU 缓存，同一文件路径只会被读取一次，显著提升高频调用场景性能。
    注意：缓存依据是路径字符串，因此路径需标准化（建议使用绝对路径）。
    """
    with open(file_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
```

---

## 🔧 使用示例

### 基本使用

```python
from autospider.extractor.llm.prompt_template import render_template

# 渲染 system_prompt
system_prompt = render_template(
    "prompts/decider.yaml",
    section="system_prompt"
)

# 渲染 user_prompt 并传入变量
user_prompt = render_template(
    "prompts/decider.yaml",
    section="user_prompt",
    variables={
        "task": "收集商品信息",
        "target_text": "价格"
    }
)
```

### 渲染整个文件

```python
# 渲染整个 YAML 文件
full_content = render_template(
    "prompts/planner.yaml",
    variables={"start_url": "https://example.com"}
)
```

### 清除缓存

```python
from autospider.extractor.llm.prompt_template import clear_template_cache

# 修改了 yaml 文件后...
clear_template_cache()
# 再次渲染将读取最新内容
```

### 获取所有 Section

```python
from autospider.extractor.llm.prompt_template import get_template_sections

sections = get_template_sections("prompts/decider.yaml")
print(sections) 
# 输出: ['system_prompt', 'user_prompt', 'examples']
```

---

## 📝 最佳实践

### 模板设计

1. **使用 YAML 格式**：使用 YAML 格式组织模板，便于管理多个 Section
2. **分离关注点**：将 system_prompt 和 user_prompt 分离到不同的 Section
3. **使用变量**：使用变量使模板更加灵活和可重用

### 性能优化

1. **利用缓存**：利用 LRU 缓存提升性能
2. **使用绝对路径**：使用绝对路径避免缓存失效
3. **合理设置缓存大小**：根据实际需求调整 LRU 缓存大小

### 兼容性考虑

1. **优先简单语法**：优先使用简单的 `{{key}}` 语法
2. **避免复杂逻辑**：避免使用复杂的循环和条件
3. **测试两种模式**：在 Jinja2 和降级模式下都进行测试

---

## 🔍 故障排除

### 常见问题

1. **模板文件未找到**
   - 检查文件路径是否正确
   - 验证文件是否存在
   - 确认文件权限是否正确

2. **变量替换失败**
   - 检查变量名是否正确
   - 验证变量是否已提供
   - 确认变量类型是否正确

3. **缓存未更新**
   - 检查是否调用了 `clear_template_cache()`
   - 验证文件路径是否一致
   - 确认文件是否真的被修改

4. **Jinja2 语法错误**
   - 检查 Jinja2 语法是否正确
   - 验证模板逻辑是否合理
   - 确认 Jinja2 是否已安装

### 调试技巧

```python
# 检查 Jinja2 是否可用
from autospider.extractor.llm.prompt_template import is_jinja2_available
print(f"Jinja2 可用: {is_jinja2_available()}")

# 检查模板文件内容
from autospider.extractor.llm.prompt_template import load_template_file
data = load_template_file("prompts/decider.yaml")
print(f"模板内容: {data}")

# 检查所有 Section
from autospider.extractor.llm.prompt_template import get_template_sections
sections = get_template_sections("prompts/decider.yaml")
print(f"所有 Section: {sections}")
```

---

## 📚 方法参考

### 核心函数

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `render_template()` | file_path, section, variables | str | 加载 YAML 模板并渲染指定部分 |
| `render_text()` | text, variables | str | 渲染一段独立的文本字符串 |
| `is_jinja2_available()` | 无 | bool | 检查是否支持 Jinja2 |
| `load_template_file()` | file_path | dict | 加载并缓存 YAML 文件 |
| `clear_template_cache()` | 无 | None | 清除文件缓存 |
| `get_template_sections()` | file_path | list[str] | 获取模板文件中的所有 Section |

---

## 📄 模板文件格式

### YAML 模板示例

```yaml
system_prompt: |
  你是一个网页自动化操作专家，擅长分析网页截图并决定下一步操作。

user_prompt: |
  ## 任务目标
  {{task}}

  ## 提取目标
  精确匹配文本「{{target_text}}」

  ## 可交互元素列表
  {{marks_text}}

examples:
  - task: "收集商品信息"
    target_text: "价格"
    action: "click"
    mark_id: 5
```

### 变量使用

```yaml
# 简单变量替换
user_prompt: |
  任务: {{task}}
  目标: {{target_text}}

# 列表遍历（需要 Jinja2）
user_prompt: |
  {% for item in items %}
  - {{item.name}}: {{item.value}}
  {% endfor %}

# 条件判断（需要 Jinja2）
user_prompt: |
  {% if show_debug %}
  调试信息: {{debug_info}}
  {% endif %}
```

---

*最后更新: 2026-01-08*
