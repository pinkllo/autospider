# Prompt Template Engine

`prompt_template.py` 是项目统一的提示词管理组件，支持动态渲染和缓存。

---

## 📑 核心函数

### `render_template(file_path, section=None, variables=None)`
加载并渲染 YAML 模板。
- `file_path`: YAML 文件的绝对或相对路径。
- `section`: YAML 中的一级 Key。如果为 `None`，则渲染整个文件内容。
- `variables`: 用于替换占位符的变量字典。

### `render_text(text, variables=None)`
渲染一段纯文本模板。
- 支持 Jinja2 语法（如果环境已安装）。
- 自动回退到 `{{key}}` 简单替换。

---

## 🏗️ 模板格式 (YAML)

```yaml
system_prompt: |
  你是一个名为 {{name}} 的智能爬虫。
  你的目标是采集 {{target}} 网站的数据。

user_prompt: |
  请分析以下页面：{{url}}
```

---

## 🚀 性能优化

- **LRU Cache**: 自动缓存已加载的模板字典，减少磁盘 IO。
- **Environment Detection**: 模块加载时检测 Jinja2，避免重复导入开销。
