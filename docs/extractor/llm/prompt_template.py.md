# Prompt Template Engine - 通用 Prompt 模板引擎

## 📋 基本信息

### 文件路径
`d:\autospider\src\autospider\extractor\llm\prompt_template.py`

### 核心功能
通用 Prompt 模板引擎，用于加载和渲染 YAML 格式的提示词模板。

### 设计理念
提供纯函数接口，支持 Jinja2 模板引擎，同时实现优雅降级机制，确保在各种环境下都能正常工作。

## 📁 函数目录

### 核心函数
- `is_jinja2_available` - 检查当前环境是否支持 Jinja2 模板引擎
- `load_template_file` - 加载并缓存 YAML 模板文件
- `clear_template_cache` - 清除模板文件的 LRU 缓存
- `render_text` - 渲染一段模板文本
- `render_template` - 加载 YAML 模板文件并渲染指定部分
- `get_template_sections` - 获取模板文件中所有可用的 Section 名称

## 🎯 核心功能详解

### is_jinja2_available()

**功能说明**：检查当前环境是否支持 Jinja2 模板引擎。

**返回值**：`bool` - 是否支持 Jinja2

**执行流程**：
- 模块加载时一次性判断 Jinja2 是否可用
- 避免重复 import 开销

### load_template_file()

**功能说明**：加载并缓存 YAML 模板文件。

**参数**：
| 参数名 | 类型 | 描述 |
|--------|------|------|
| file_path | `str` | YAML 模板文件的完整路径 |

**返回值**：`dict[str, Any]` - YAML 文件解析后的字典对象

**特性**：
- 使用 LRU 缓存，同一文件路径只会被读取一次
- 显著提升高频调用场景性能
- 缓存依据是路径字符串，建议使用绝对路径

### clear_template_cache()

**功能说明**：清除模板文件的 LRU 缓存。

**适用场景**：
- 开发调试场景
- 当模板文件内容更新后调用此函数生效

### render_text()

**功能说明**：渲染一段模板文本。

**参数**：
| 参数名 | 类型 | 描述 |
|--------|------|------|
| text | `str` | 包含占位符 (如 {{name}}) 的原始文本 |
| variables | `dict[str, Any] | None` | 变量字典，用于替换模板中的占位符 |

**返回值**：`str` - 渲染后的完整文本

**执行流程**：
1. 如果没有变量，直接返回原始文本
2. 如果 Jinja2 可用，使用 Jinja2 渲染（支持完整模板语法）
3. 如果 Jinja2 不可用，回退到简单的 {{key}} 占位符替换

### render_template()

**功能说明**：加载 YAML 模板文件并渲染指定部分，是最核心的对外接口。

**参数**：
| 参数名 | 类型 | 描述 |
|--------|------|------|
| file_path | `str` | YAML 模板文件的完整路径 |
| section | `str | None` | 要渲染的 YAML 一级 Key（如 'system_prompt', 'user_prompt'） |
| variables | `dict[str, Any] | None` | 变量字典 |

**返回值**：`str` - 渲染后的 Prompt 文本

**执行流程**：
1. 加载模板文件（使用缓存）
2. 提取指定 Section 的内容
3. 如果 Section 内容不是字符串，转为 YAML 字符串
4. 渲染文本
5. 返回渲染后的结果

### get_template_sections()

**功能说明**：获取模板文件中所有可用的 Section 名称（一级 Key 列表）。

**参数**：
| 参数名 | 类型 | 描述 |
|--------|------|------|
| file_path | `str` | YAML 模板文件路径 |

**返回值**：`list[str]` - 该模板文件的所有一级 Key 列表

**适用场景**：
- 枚举模板文件结构
- 便于动态选择 Section

## 🚀 特性说明

### Jinja2 优先
- 若安装了 jinja2，则启用全部模板功能（循环、条件、过滤器等）
- 支持复杂的模板逻辑
- 提供更灵活的模板编写方式

### 优雅降级
- 若未安装 jinja2，自动回退到简单的 {{key}} 占位符替换
- 确保在各种环境下都能正常工作
- 减少依赖，降低部署复杂度

### 路径透明
- 所有路径由调用方传入，无任何默认路径假设
- 提高模块的灵活性和可复用性
- 便于在不同项目中使用

### 性能优化
- 使用 LRU 缓存，减少文件读取次数
- 模块加载时一次性判断 Jinja2 是否可用
- 避免重复 import 开销

### 灵活的配置
- 支持渲染整个模板或指定 Section
- 支持将非字符串 Section 内容转为 YAML 字符串
- 支持多种变量类型

## 💡 使用示例

### 基本使用

```python
from autospider.extractor.llm.prompt_template import render_template

# 渲染模板文件中的 system_prompt 部分
prompt = render_template(
    "prompts/decider.yaml",
    section="system_prompt",
    variables={"task": "查找并点击登录按钮"}
)

print(prompt)
```

### 渲染整个模板

```python
from autospider.extractor.llm.prompt_template import render_template

# 渲染整个模板（不指定 section）
full_template = render_template(
    "prompts/simple.yaml",
    variables={"name": "test"}
)

print(full_template)
```

### 检查 Jinja2 可用性

```python
from autospider.extractor.llm.prompt_template import is_jinja2_available

if is_jinja2_available():
    print("Jinja2 可用，可以使用完整模板功能")
else:
    print("Jinja2 不可用，将使用简单占位符替换")
```

### 获取模板 Sections

```python
from autospider.extractor.llm.prompt_template import get_template_sections

# 获取模板文件中所有可用的 Section
sections = get_template_sections("prompts/decider.yaml")
print(f"可用 Sections: {sections}")

# 渲染所有 Sections
for section in sections:
    prompt = render_template(
        "prompts/decider.yaml",
        section=section,
        variables={"task": "测试任务"}
    )
    print(f"\n--- {section} ---")
    print(prompt)
```

### 清除缓存

```python
from autospider.extractor.llm.prompt_template import clear_template_cache

# 清除模板缓存（开发调试时使用）
clear_template_cache()
print("模板缓存已清除")
```

## 🔍 最佳实践

### 模板文件设计

1. **使用 YAML 格式**：便于组织和维护
2. **分 Section 管理**：将不同类型的 Prompt 分为不同 Section
3. **使用变量占位符**：便于动态替换内容
4. **保持模板简洁**：避免过于复杂的模板逻辑

### 变量命名

1. **使用清晰的变量名**：便于理解和维护
2. **避免冲突**：确保变量名在模板中唯一
3. **使用一致的命名风格**：建议使用下划线命名法

### 性能优化

1. **使用绝对路径**：确保缓存正常工作
2. **避免频繁调用 clear_template_cache**：只在开发调试时使用
3. **复用变量**：减少重复的变量定义

### 开发调试

1. **检查 Jinja2 可用性**：在开发环境中确保 Jinja2 可用，充分利用其功能
2. **测试模板渲染**：在开发过程中测试模板渲染结果
3. **使用明确的错误信息**：便于调试模板问题

## 🐛 故障排除

### 问题：模板渲染失败

**可能原因**：
1. 文件路径错误
2. Section 名称错误
3. 变量类型不匹配
4. Jinja2 模板语法错误

**解决方案**：
1. 检查文件路径是否正确
2. 使用 get_template_sections() 查看可用 Section
3. 检查变量类型是否与模板要求匹配
4. 检查 Jinja2 模板语法是否正确

### 问题：缓存不生效

**可能原因**：
1. 使用相对路径，导致路径不一致
2. 频繁调用 clear_template_cache()

**解决方案**：
1. 使用绝对路径
2. 减少 clear_template_cache() 的调用次数

### 问题：Jinja2 功能不可用

**可能原因**：
1. 未安装 Jinja2
2. Jinja2 版本不兼容

**解决方案**：
1. 安装 Jinja2：pip install jinja2
2. 检查 Jinja2 版本，确保兼容

### 问题：模板变量替换不生效

**可能原因**：
1. 变量名拼写错误
2. 变量类型错误
3. 模板语法错误

**解决方案**：
1. 检查变量名拼写
2. 检查变量类型
3. 检查模板语法

## 📚 函数参考

### 核心函数

| 函数名 | 参数 | 返回值 | 描述 |
|--------|------|--------|------|
| `is_jinja2_available` | None | `bool` | 检查当前环境是否支持 Jinja2 模板引擎 |
| `load_template_file` | file_path | `dict[str, Any]` | 加载并缓存 YAML 模板文件 |
| `clear_template_cache` | None | None | 清除模板文件的 LRU 缓存 |
| `render_text` | text, variables=None | `str` | 渲染一段模板文本 |
| `render_template` | file_path, section=None, variables=None | `str` | 加载 YAML 模板文件并渲染指定部分 |
| `get_template_sections` | file_path | `list[str]` | 获取模板文件中所有可用的 Section 名称 |

## 🔄 依赖关系

- `yaml` - YAML 解析
- `typing` - 类型注解
- `functools.lru_cache` - 缓存功能
- `jinja2` - 可选依赖，用于高级模板功能

## 📝 设计模式

- **纯函数模式**：所有函数都是纯函数，无副作用
- **策略模式**：根据环境选择不同的渲染策略（Jinja2 或简单替换）
- **缓存模式**：使用 LRU 缓存优化性能
- **降级模式**：在不支持 Jinja2 的环境下自动降级

## 🚀 性能优化

### 时间复杂度
- `load_template_file`：O(n)，其中 n 是文件大小（首次调用）；O(1)（缓存命中）
- `render_text`：O(n)，其中 n 是文本长度
- `render_template`：O(n)，其中 n 是模板文件大小
- `get_template_sections`：O(1)（缓存命中）；O(n)（首次调用）

### 空间复杂度
- O(n)，其中 n 是模板文件大小和缓存大小

### 优化建议

1. **使用绝对路径**：确保缓存正常工作
2. **减少文件读取次数**：利用缓存机制
3. **避免频繁清除缓存**：只在开发调试时使用
4. **使用合适的模板复杂度**：避免过于复杂的模板逻辑

## 📌 版本历史

| 版本 | 更新内容 | 日期 |
|------|----------|------|
| 1.0 | 初始版本 | 2026-01-01 |
| 1.1 | 增加 LRU 缓存 | 2026-01-10 |
| 1.2 | 支持渲染整个模板 | 2026-01-15 |
| 1.3 | 优化 Jinja2 检测 | 2026-01-18 |
| 1.4 | 增加 get_template_sections 函数 | 2026-01-19 |

## 🔮 未来规划

- 支持更多模板格式（如 JSON、TOML）
- 提供更丰富的模板函数
- 支持模板继承
- 提供更详细的错误信息
- 支持模板热重载

## 📄 许可证

MIT License

---

最后更新: 2026-01-19