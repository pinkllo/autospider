# Prompts 模块

Prompts 模块是 AutoSpider 的提示词管理中枢，包含所有与大语言模型交互的 Prompt 模板。该模块采用模块化设计，每个功能模块都有独立的 Prompt 文件夹，便于管理和维护。

---

## 📁 模块结构

```
prompts/
├── __init__.py              # 模块导出
├── agent/                   # Agent 相关 Prompt
│   ├── __init__.py
│   ├── agent.yaml           # Agent 决策 Prompt
│   └── action.yaml         # 动作执行 Prompt
├── crawler/                 # 爬虫相关 Prompt
│   ├── __init__.py
│   ├── url_collector.yaml   # URL 收集 Prompt
│   └── batch_collector.yaml # 批量爬取 Prompt
├── extractor/               # 提取器相关 Prompt
│   ├── __init__.py
│   ├── config_generator.yaml # 配置生成 Prompt
│   └── rule_generator.yaml  # 规则生成 Prompt
└── utils/                   # 工具 Prompt
    ├── __init__.py
    └── xpath_generator.yaml # XPath 生成 Prompt
```

---

## 📑 函数目录

### 🎯 Agent Prompt (agent/)
- `agent.yaml` - Agent 决策 Prompt，用于生成下一步动作
- `action.yaml` - 动作执行 Prompt，用于执行具体动作

### 🔍 Crawler Prompt (crawler/)
- `url_collector.yaml` - URL 收集 Prompt，用于发现详情页 URL
- `batch_collector.yaml` - 批量爬取 Prompt，用于批量数据采集

### 📊 Extractor Prompt (extractor/)
- `config_generator.yaml` - 配置生成 Prompt，用于生成爬虫配置
- `rule_generator.yaml` - 规则生成 Prompt，用于生成提取规则

### 🛠️ Utils Prompt (utils/)
- `xpath_generator.yaml` - XPath 生成 Prompt，用于生成 XPath 选择器

---

## 🚀 核心功能

### Prompt 模板系统

使用 YAML 格式存储 Prompt 模板，支持多部分定义和变量替换。

```yaml
# agent.yaml 示例
system_prompt: |
  你是一个智能网页自动化助手，负责分析页面并执行操作。

user_prompt: |
  当前任务: {{task}}
  页面截图: [截图]
  标注元素:
  {% for mark in marks %}
  - [{{mark.mark_id}}] {{mark.tag}}: {{mark.text}}
  {% endfor %}

  请分析页面并决定下一步操作。

examples: |
  示例 1:
  用户: 点击登录按钮
  助手: {"action": "click", "mark_id": 5, "thinking": "点击登录按钮提交表单"}
```

### Prompt 渲染

使用 Prompt 渲染器加载和渲染模板：

```python
from autospider.prompts import load_prompt, render_prompt

# 加载 Prompt 模板
prompt_template = load_prompt("agent/agent.yaml")

# 渲染 Prompt
rendered_prompt = render_prompt(
    template=prompt_template,
    section="user_prompt",
    variables={
        "task": "点击登录按钮",
        "marks": [
            {"mark_id": 5, "tag": "button", "text": "登录"}
        ]
    }
)

print(f"渲染后的 Prompt: {rendered_prompt}")
```

---

## 💡 特性说明

### 模块化设计

每个功能模块都有独立的 Prompt 文件夹，便于管理和维护：

```
prompts/
├── agent/          # Agent 相关 Prompt
├── crawler/        # 爬虫相关 Prompt
├── extractor/      # 提取器相关 Prompt
└── utils/          # 工具 Prompt
```

### 多部分定义

支持在单个 YAML 文件中定义多个 Prompt 部分：

```yaml
system_prompt: |
  系统提示词...

user_prompt: |
  用户提示词...

examples: |
  示例...

output_format: |
  输出格式...
```

### 变量替换

支持使用 Jinja2 语法进行变量替换：

```yaml
user_prompt: |
  任务: {{task}}
  URL: {{url}}
  字段:
  {% for field in fields %}
  - {{field}}
  {% endfor %}
```

---

## 🔧 使用示例

### 加载和渲染 Prompt

```python
from autospider.prompts import load_prompt, render_prompt

async def use_prompt_template():
    """使用 Prompt 模板"""

    # 加载 Agent Prompt
    agent_prompt = load_prompt("agent/agent.yaml")

    # 渲染用户 Prompt
    user_prompt = render_prompt(
        template=agent_prompt,
        section="user_prompt",
        variables={
            "task": "点击登录按钮",
            "marks": [
                {"mark_id": 5, "tag": "button", "text": "登录"},
                {"mark_id": 6, "tag": "input", "text": "用户名"}
            ]
        }
    )

    # 渲染系统 Prompt
    system_prompt = render_prompt(
        template=agent_prompt,
        section="system_prompt",
        variables={}
    )

    print(f"系统 Prompt: {system_prompt}")
    print(f"用户 Prompt: {user_prompt}")

# 使用示例
asyncio.run(use_prompt_template())
```

### 自定义 Prompt

```python
from autospider.prompts import create_prompt, save_prompt

async def create_custom_prompt():
    """创建自定义 Prompt"""

    # 创建 Prompt 模板
    custom_prompt = {
        "system_prompt": "你是一个专业的数据提取助手",
        "user_prompt": """
        任务: {{task}}
        页面: {{url}}
        请提取以下字段:
        {% for field in fields %}
        - {{field}}
        {% endfor %}
        """,
        "output_format": """
        请以 JSON 格式输出:
        {
          "field1": "value1",
          "field2": "value2"
        }
        """
    }

    # 保存 Prompt
    save_prompt("custom/custom_extractor.yaml", custom_prompt)

    print("自定义 Prompt 已保存")

# 使用示例
asyncio.run(create_custom_prompt())
```

---

## 📝 最佳实践

### Prompt 设计

1. **清晰明确**：使用清晰、具体的语言
2. **结构化输出**：要求 LLM 输出结构化数据
3. **示例引导**：提供示例引导 LLM 理解
4. **约束条件**：明确说明约束条件

### 模板管理

1. **模块化**：按功能模块组织 Prompt
2. **命名规范**：使用清晰的文件命名
3. **版本控制**：使用版本控制系统管理 Prompt
4. **文档说明**：为每个 Prompt 添加说明文档

### 变量设计

1. **一致性**：使用一致的变量命名
2. **完整性**：确保所有必需变量都有定义
3. **默认值**：为可选变量提供默认值
4. **类型检查**：验证变量类型是否正确

---

## 🔍 故障排除

### 常见问题

1. **Prompt 加载失败**
   - 检查文件路径是否正确
   - 验证 YAML 格式是否正确
   - 确认文件是否存在

2. **Prompt 渲染失败**
   - 检查变量是否完整
   - 验证 Jinja2 语法是否正确
   - 确认模板格式是否正确

3. **LLM 响应不符合预期**
   - 检查 Prompt 是否清晰明确
   - 验证示例是否正确
   - 调整 Prompt 描述

### 调试技巧

```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 检查 Prompt 模板
print(f"Prompt 模板: {prompt_template}")
print(f"Prompt 部分: {prompt_template.keys()}")

# 检查渲染结果
print(f"渲染后的 Prompt: {rendered_prompt}")
print(f"Prompt 长度: {len(rendered_prompt)}")

# 检查变量
print(f"变量: {variables}")
```

---

## 📚 Prompt 模板示例

### Agent 决策 Prompt

```yaml
system_prompt: |
  你是一个智能网页自动化助手，负责分析页面并执行操作。

user_prompt: |
  当前任务: {{task}}
  页面截图: [截图]
  标注元素:
  {% for mark in marks %}
  - [{{mark.mark_id}}] {{mark.tag}}: {{mark.text}}
  {% endfor %}

  请分析页面并决定下一步操作。

examples: |
  示例 1:
  用户: 点击登录按钮
  助手: {"action": "click", "mark_id": 5, "thinking": "点击登录按钮提交表单"}

  示例 2:
  用户: 在搜索框输入"AutoSpider"
  助手: {"action": "type", "mark_id": 3, "text": "AutoSpider", "thinking": "在搜索框中输入关键词"}

output_format: |
  请以 JSON 格式输出:
  {
    "action": "动作类型",
    "mark_id": 元素标记ID,
    "text": "输入文本（如果需要）",
    "thinking": "思考过程"
  }
```

### URL 收集 Prompt

```yaml
system_prompt: |
  你是一个专业的网页数据提取助手，负责从列表页收集详情页 URL。

user_prompt: |
  任务: {{task}}
  列表页 URL: {{list_url}}
  页面截图: [截图]
  标注元素:
  {% for mark in marks %}
  - [{{mark.mark_id}}] {{mark.tag}}: {{mark.text}}
  {% endfor %}

  请识别详情页链接并收集 URL。

examples: |
  示例 1:
  用户: 收集商品详情页 URL
  助手: {
    "detail_urls": [
      "https://example.com/product/123",
      "https://example.com/product/456"
    ],
    "common_xpath": "//a[@class='product-link']"
  }

output_format: |
  请以 JSON 格式输出:
  {
    "detail_urls": ["url1", "url2", ...],
    "common_xpath": "公共 XPath 选择器"
  }
```

---

*最后更新: 2026-01-08*
