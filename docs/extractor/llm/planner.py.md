# Task Planner - 任务规划器

## 📋 基本信息

### 文件路径
`d:\autospider\src\autospider\extractor\llm\planner.py`

### 核心功能
任务规划器，用于在执行前分析任务并生成执行计划。

### 设计理念
在执行任务前，通过 LLM 分析任务需求，生成结构化的执行计划，指导后续的浏览器操作。

## 📁 函数目录

### 数据模型
- `TaskPlan` - 任务执行计划模型

### 主类
- `TaskPlanner` - 任务规划器

### 核心方法
- `plan` - 分析任务并生成执行计划
- `_parse_response` - 解析 LLM 响应

## 🎯 核心功能详解

### TaskPlan 数据模型

**功能说明**：任务执行计划数据模型，定义了执行计划的结构。

**字段说明**：
| 字段名 | 类型 | 描述 |
|--------|------|------|
| task_analysis | `str` | 任务分析 |
| steps | `list[str]` | 执行步骤列表 |
| target_description | `str` | 目标描述 |
| success_criteria | `str` | 成功标准 |
| potential_challenges | `list[str]` | 潜在挑战 |

### TaskPlanner 类

**功能说明**：任务规划器，负责分析任务并生成执行计划。

**初始化参数**：
| 参数名 | 类型 | 描述 | 默认值 |
|--------|------|------|--------|
| api_key | `str | None` | API Key | None |
| api_base | `str | None` | API Base URL | None |
| model | `str | None` | 模型名称 | None |

**核心属性**：
| 属性名 | 类型 | 描述 |
|--------|------|------|
| api_key | `str` | API Key（优先使用参数，其次使用 planner 专用配置，最后使用主配置） |
| api_base | `str` | API Base URL（同上） |
| model | `str` | 模型名称（同上） |
| llm | `ChatOpenAI` | LangChain OpenAI 聊天模型实例 |

### 核心方法

#### plan()
**功能**：分析任务并生成执行计划。

**参数**：
| 参数名 | 类型 | 描述 |
|--------|------|------|
| start_url | `str` | 起始 URL |
| task | `str` | 任务描述 |
| target_text | `str` | 目标提取文本 |

**返回值**：`TaskPlan` - 执行计划对象

**执行流程**：
1. 使用模板引擎加载和渲染 prompt
2. 调用 LLM 生成执行计划
3. 解析 LLM 响应
4. 返回结构化的执行计划

#### _parse_response()
**功能**：解析 LLM 响应，提取执行计划。

**参数**：
| 参数名 | 类型 | 描述 |
|--------|------|------|
| response_text | `str` | LLM 响应文本 |
| task | `str` | 原始任务描述 |
| target_text | `str` | 原始目标文本 |

**返回值**：`TaskPlan` - 执行计划对象

**执行流程**：
1. 清理 markdown 代码块
2. 提取 JSON 内容
3. 解析 JSON 数据
4. 构建 TaskPlan 对象
5. 如果解析失败，返回默认计划

## 🚀 特性说明

### 智能任务分析
- 通过 LLM 理解任务需求
- 生成结构化的执行步骤
- 识别潜在挑战和成功标准

### 灵活的配置管理
- 支持参数化配置
- 支持 planner 专用配置
- 支持主配置 fallback
- 确保配置的灵活性和可扩展性

### 模板化 Prompt
- 使用 YAML 模板文件管理 prompt
- 支持动态变量替换
- 方便修改和维护
- 提高 prompt 的复用性

### 鲁棒的响应解析
- 支持多种响应格式
- 自动清理 markdown 代码块
- 容错处理，解析失败时返回默认计划
- 确保系统的稳定性

## 💡 使用示例

### 基本使用

```python
from autospider.extractor.llm.planner import TaskPlanner

async def main():
    # 创建任务规划器实例
    planner = TaskPlanner()
    
    # 生成执行计划
    plan = await planner.plan(
        start_url="https://example.com",
        task="查找并点击登录按钮",
        target_text="欢迎登录"
    )
    
    # 打印执行计划
    print(f"任务分析: {plan.task_analysis}")
    print(f"执行步骤: {plan.steps}")
    print(f"目标描述: {plan.target_description}")
    print(f"成功标准: {plan.success_criteria}")
    print(f"潜在挑战: {plan.potential_challenges}")

if __name__ == "__main__":
    asyncio.run(main())
```

### 自定义配置

```python
from autospider.extractor.llm.planner import TaskPlanner

async def main():
    # 使用自定义配置创建任务规划器
    planner = TaskPlanner(
        api_key="your-api-key",
        api_base="https://api.example.com/v1",
        model="gpt-4"
    )
    
    # 生成执行计划
    plan = await planner.plan(
        start_url="https://example.com",
        task="查找并点击登录按钮",
        target_text="欢迎登录"
    )
    
    # 使用执行计划指导后续操作
    for i, step in enumerate(plan.steps, 1):
        print(f"执行步骤 {i}: {step}")
        # 执行浏览器操作
        # ...

if __name__ == "__main__":
    asyncio.run(main())
```

## 🔍 最佳实践

### Prompt 模板优化

- 定期更新 prompt 模板，提高计划生成质量
- 根据任务类型调整 prompt 内容
- 结合实际执行情况，优化 prompt 结构

### 模型选择

- 对于复杂任务，建议使用更强大的模型（如 GPT-4）
- 对于简单任务，可以使用更高效的模型
- 根据实际需求调整模型参数

### 错误处理

- 处理 LLM 响应解析失败的情况
- 为不同类型的任务准备默认执行计划
- 监控计划执行情况，及时调整

### 性能优化

- 缓存常用任务的执行计划
- 优化 prompt 结构，减少 LLM 调用时间
- 合理设置温度参数，平衡创造力和准确性

## 🐛 故障排除

### 问题：计划生成质量不高

**可能原因**：
1. prompt 模板不够优化
2. 模型选择不当
3. 任务描述不够清晰

**解决方案**：
1. 优化 prompt 模板
2. 尝试使用更强大的模型
3. 提供更详细的任务描述

### 问题：响应解析失败

**可能原因**：
1. LLM 响应格式不一致
2. 正则表达式不够健壮
3. JSON 格式错误

**解决方案**：
1. 优化响应解析逻辑
2. 增强正则表达式
3. 添加更容错的解析机制

### 问题：API 调用失败

**可能原因**：
1. API Key 无效
2. API Base URL 错误
3. 网络连接问题
4. 模型不存在

**解决方案**：
1. 检查 API Key 是否有效
2. 验证 API Base URL
3. 检查网络连接
4. 确认模型名称正确

## 📚 方法参考

### TaskPlanner 类方法

| 方法名 | 参数 | 返回值 | 描述 |
|--------|------|--------|------|
| `__init__` | api_key=None, api_base=None, model=None | None | 初始化任务规划器 |
| `plan` | start_url, task, target_text | `TaskPlan` | 分析任务并生成执行计划 |
| `_parse_response` | response_text, task, target_text | `TaskPlan` | 解析 LLM 响应 |

## 🔄 依赖关系

- `langchain_core` - LangChain 核心库
- `langchain_openai` - OpenAI 集成
- `pydantic` - 数据验证和模型定义
- `re` - 正则表达式处理
- `json` - JSON 解析
- `pathlib` - 文件路径处理

## 📝 设计模式

- **模板方法模式**：使用模板引擎渲染 prompt
- **策略模式**：支持不同的模型配置
- **工厂模式**：动态创建 LLM 实例
- **数据模型模式**：使用 Pydantic 定义数据结构

## 🚀 性能优化

### 时间复杂度
- 模型调用：O(1)（API 调用）
- 响应解析：O(n)，其中 n 是响应文本长度

### 空间复杂度
- O(n)，其中 n 是响应文本长度

### 优化建议

1. **缓存常用任务的执行计划**：减少重复的 API 调用
2. **优化 prompt 结构**：减少不必要的 token 消耗
3. **使用更高效的模型**：根据任务复杂度选择合适的模型
4. **异步调用**：支持并发执行，提高效率

## 📌 版本历史

| 版本 | 更新内容 | 日期 |
|------|----------|------|
| 1.0 | 初始版本 | 2026-01-01 |
| 1.1 | 支持 planner 专用配置 | 2026-01-10 |
| 1.2 | 优化响应解析逻辑 | 2026-01-15 |
| 1.3 | 支持 YAML 模板文件 | 2026-01-18 |

## 🔮 未来规划

- 支持更多模型提供商
- 支持计划的动态调整
- 支持计划的序列化和持久化
- 支持多任务并行规划
- 提供更丰富的计划类型

## 📄 许可证

MIT License

---

最后更新: 2026-01-19