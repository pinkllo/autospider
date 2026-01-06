# Prompt 模板系统使用说明

## 概述

本项目已将所有 LLM 的 prompt 从代码中分离出来，统一使用 YAML 配置文件管理，通过通用的 Prompt 模板引擎 (`llm/prompt_template.py`) 加载和渲染。

## 目录结构

```
autospider/
├── prompts/                        # Prompt 模板配置目录
│   ├── planner.yaml               # 任务规划器的 prompts
│   ├── decider.yaml               # LLM 决策器的 prompts
│   ├── url_collector.yaml         # URL 收集器的 prompts
│   └── script_generator.yaml      # 脚本生成器的 prompts
├── src/
│   └── autospider/
│       └── llm/
│           └── prompt_template.py  # 通用模板引擎
```

## Prompt 模板引擎 API

### 核心函数

#### `render_template(file_path, section, variables)`

加载 YAML 模板文件并渲染指定部分。

**参数：**
- `file_path` (str): YAML 模板文件的完整路径
- `section` (str, 可选): 要渲染的 YAML 一级 Key（如 'system_prompt', 'user_prompt'）
- `variables` (dict, 可选): 变量字典，用于替换模板中的占位符

**返回：**
- str: 渲染后的 Prompt 文本

**示例：**

```python
from pathlib import Path
from llm.prompt_template import render_template

# 定义模板文件路径
PROMPT_TEMPLATE_PATH = str(Path(__file__).parent.parent / "prompts" / "planner.yaml")

# 渲染 system_prompt（无变量）
system_prompt = render_template(
    PROMPT_TEMPLATE_PATH,
    section="system_prompt",
)

# 渲染 user_prompt（带变量）
user_prompt = render_template(
    PROMPT_TEMPLATE_PATH,
    section="user_prompt",
    variables={
        "start_url": "https://example.com",
        "task": "收集详情页 URL",
        "target_text": "已中标",
    }
)
```

### 其他辅助函数

- `is_jinja2_available()`: 检查当前环境是否支持 Jinja2
- `load_template_file(file_path)`: 加载并缓存 YAML 模板文件
- `clear_template_cache()`: 清除模板文件的 LRU 缓存
- `render_text(text, variables)`: 渲染一段模板文本
- `get_template_sections(file_path)`: 获取模板文件中所有可用的 Section 名称

## YAML 模板文件格式

每个 YAML 文件包含多个 section，每个 section 是一个独立的 prompt 模板。

**示例：**

```yaml
# system_prompt section
system_prompt: |
  你是一个专业的网页自动化任务规划专家。

# user_prompt section（支持变量）
user_prompt: |
  你是一个网页自动化任务规划专家。根据用户的任务描述和目标，分析任务并制定执行计划。

  ## 输入
  - 起始URL: {{start_url}}
  - 任务描述: {{task}}
  - 提取目标文本: {{target_text}}

  ## 输出要求
  以JSON格式输出任务规划...
```

## 变量占位符语法

### 基础语法（兼容模式）

如果未安装 Jinja2，模板引擎会使用简单的字符串替换：

```yaml
user_prompt: |
  当前页面: {{current_url}}
  任务描述: {{task_description}}
```

### 高级语法（Jinja2 模式）

如果安装了 Jinja2，可以使用完整的 Jinja2 模板语法：

```yaml
user_prompt: |
  ## 已收集的 URL 列表
  {% for url in urls %}
  - {{ url }}
  {% endfor %}
  
  {% if target_found %}
  ⚠️ 已找到目标！
  {% else %}
  继续搜索...
  {% endif %}
```

**安装 Jinja2：**
```bash
pip install jinja2
```

## 已配置的 Prompt 模板

### 1. planner.yaml - 任务规划器

**Sections:**
- `system_prompt`: 系统提示词
- `user_prompt`: 用户提示词（变量：start_url, task, target_text）

### 2. decider.yaml - LLM 决策器

**Sections:**
- `system_prompt`: 系统提示词（包含完整的决策规则）

### 3. url_collector.yaml - URL 收集器

**Sections:**
- `ask_llm_decision_system_prompt`: 询问 LLM 决定如何获取详情页 URL
- `ask_llm_decision_user_message`: 用户消息（变量：task_description, current_url, visited_count, collected_urls_str）
- `pagination_llm_system_prompt`: 使用 LLM 视觉识别分页控件
- `pagination_llm_user_message`: 分页识别的用户消息

### 4. script_generator.yaml - 脚本生成器

**Sections:**
- `system_prompt`: 系统提示词
- `user_prompt`: 用户提示词（变量：task_description, list_url, nav_summary, visits_count, visits_summary, urls_count, url_samples, url_pattern_analysis）

## 如何添加新的 Prompt 模板

### 1. 创建新的 YAML 文件

在 `prompts/` 目录下创建新的 YAML 文件，例如 `my_module.yaml`：

```yaml
# my_module.yaml
system_prompt: |
  你是一个专业的助手。

task_prompt: |
  ## 任务
  请帮我完成以下任务：{{task_name}}
  
  ## 详细信息
  {{task_details}}
```

### 2. 在代码中使用

```python
from pathlib import Path
from llm.prompt_template import render_template

# 定义模板路径
PROMPT_TEMPLATE_PATH = str(Path(__file__).parent.parent / "prompts" / "my_module.yaml")

# 加载和渲染
system_prompt = render_template(
    PROMPT_TEMPLATE_PATH,
    section="system_prompt",
)

task_prompt = render_template(
    PROMPT_TEMPLATE_PATH,
    section="task_prompt",
    variables={
        "task_name": "数据分析",
        "task_details": "分析用户行为数据",
    }
)
```

## 修改现有 Prompt

### 方式 1: 直接编辑 YAML 文件（推荐）

直接在 `prompts/*.yaml` 文件中修改 prompt 内容，无需修改代码。

### 方式 2: 代码中覆盖

如果需要在特定情况下覆盖模板：

```python
# 加载默认模板
default_prompt = render_template(PROMPT_TEMPLATE_PATH, section="system_prompt")

# 根据条件修改
if special_case:
    system_prompt = default_prompt + "\n\n额外的指示：..."
else:
    system_prompt = default_prompt
```

## 调试技巧

### 查看所有可用的 sections

```python
from llm.prompt_template import get_template_sections

sections = get_template_sections(PROMPT_TEMPLATE_PATH)
print(f"可用的 sections: {sections}")
```

### 清除缓存（开发调试）

```python
from llm.prompt_template import clear_template_cache

# 修改 YAML 文件后清除缓存
clear_template_cache()
```

### 检查渲染结果

```python
prompt = render_template(
    PROMPT_TEMPLATE_PATH,
    section="user_prompt",
    variables={"key": "value"}
)

print("渲染后的 Prompt:")
print("=" * 60)
print(prompt)
print("=" * 60)
```

## 最佳实践

1. **分离关注点**：每个模块的 prompts 独立管理在自己的 YAML 文件中
2. **使用有意义的 section 名称**：如 `system_prompt`, `user_prompt`, `error_message` 等
3. **添加注释**：在 YAML 文件中使用 `#` 添加注释说明 prompt 的用途
4. **版本控制**：将 prompts 目录纳入版本控制，跟踪 prompt 的变更历史
5. **测试变更**：修改 prompt 后，测试对应功能是否正常工作
6. **保持简洁**：避免在单个 prompt 中包含过多逻辑，考虑拆分为多个 section

## 优势

相比硬编码在代码中，使用模板系统有以下优势：

1. **易于维护**：集中管理所有 prompts，修改无需改代码
2. **可读性强**：YAML 格式清晰易读，支持多行文本
3. **团队协作**：非开发人员也可以调整 prompts
4. **版本控制**：便于跟踪 prompt 的变更历史
5. **性能优化**：LRU 缓存减少重复文件读取
6. **灵活性高**：支持简单变量替换和 Jinja2 高级模板语法
7. **易于测试**：可以单独测试 prompt 模板的渲染效果
