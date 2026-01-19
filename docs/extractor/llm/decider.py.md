# LLM Decider - 多模态 LLM 决策器

## 📋 基本信息

### 文件路径
`d:\autospider\src\autospider\extractor\llm\decider.py`

### 核心功能
多模态 LLM 决策器，负责根据当前状态和截图决定下一步操作，是 AutoSpider 的核心决策组件。

### 设计理念
通过多模态 LLM 分析页面截图和状态信息，生成智能决策，指导浏览器自动化操作。

## 📁 函数目录

### 主类
- `LLMDecider` - 多模态 LLM 决策器

### 核心方法
- `decide` - 根据当前状态和截图决定下一步操作
- `_build_user_message` - 构建用户消息
- `_parse_response` - 解析 LLM 响应
- `_build_multimodal_content` - 构建包含历史截图的多模态消息内容
- `_detect_loop` - 检测循环操作模式

### 辅助方法
- `is_page_fully_scrolled` - 检查页面是否已被完整滚动过
- `get_page_scroll_status` - 获取页面滚动状态描述
- `_save_screenshot_to_history` - 保存截图到历史记录

## 🎯 核心功能详解

### LLMDecider 类

**功能说明**：多模态 LLM 决策器，负责根据当前状态和截图决定下一步操作。

**初始化参数**：
| 参数名 | 类型 | 描述 | 默认值 |
|--------|------|------|--------|
| api_key | `str | None` | API Key | None |
| api_base | `str | None` | API Base URL | None |
| model | `str | None` | 模型名称 | None |
| history_screenshots | `int` | 发送最近几步的截图 | 3 |

**核心属性**：
| 属性名 | 类型 | 描述 |
|--------|------|------|
| api_key | `str` | API Key |
| api_base | `str` | API Base URL |
| model | `str` | 模型名称 |
| llm | `ChatOpenAI` | LangChain OpenAI 聊天模型实例 |
| task_plan | `str | None` | 任务计划 |
| action_history | `list[dict]` | 历史操作记录 |
| scroll_count | `int` | 滚动计数器 |
| page_scroll_history | `dict[str, dict]` | 页面滚动历史 |
| current_page_url | `str` | 当前页面 URL |
| recent_action_signatures | `list[str]` | 最近的操作序列 |
| screenshot_history | `list[dict]` | 截图历史 |

### 核心方法

#### decide()
**功能**：根据当前状态和截图决定下一步操作。

**参数**：
| 参数名 | 类型 | 描述 |
|--------|------|------|
| state | `AgentState` | Agent 状态 |
| screenshot_base64 | `str` | 带 SoM 标注的截图（Base64） |
| marks_text | `str` | 格式化的 marks 文本描述 |
| target_found_in_page | `bool` | 页面中是否发现了目标文本 |
| scroll_info | `ScrollInfo | None` | 页面滚动状态信息 |

**返回值**：`Action` - 下一步操作对象

**执行流程**：
1. 构建用户消息
2. 构建包含历史截图的多模态消息内容
3. 调用 LLM 生成决策
4. 解析 LLM 响应
5. 更新页面滚动历史
6. 检测循环操作模式
7. 记录操作历史
8. 保存截图到历史
9. 返回操作对象

#### _build_user_message()
**功能**：构建用户消息，包含任务计划、任务目标、滚动状态等信息。

**参数**：
| 参数名 | 类型 | 描述 |
|--------|------|------|
| state | `AgentState` | Agent 状态 |
| marks_text | `str` | 格式化的 marks 文本描述 |
| target_found_in_page | `bool` | 页面中是否发现了目标文本 |
| scroll_info | `ScrollInfo | None` | 页面滚动状态信息 |

**返回值**：`str` - 构建好的用户消息

**核心内容**：
- 任务计划和目标
- 目标文本是否已在页面中找到
- 循环检测警告
- 滚动次数警告
- 页面滚动状态
- 历史操作记录
- 上一步结果
- 可交互元素列表

#### _parse_response()
**功能**：解析 LLM 响应，生成 Action 对象。

**参数**：
| 参数名 | 类型 | 描述 |
|--------|------|------|
| response_text | `str` | LLM 响应文本 |

**返回值**：`Action` - 解析后的操作对象

**执行流程**：
1. 从 LLM 响应中提取 JSON 数据
2. 兼容处理不同的输出结构
3. 解析 action 类型
4. 自动推断缺失的 action 类型
5. 解析 scroll_delta 等参数
6. 构建并返回 Action 对象

#### _build_multimodal_content()
**功能**：构建包含历史截图的多模态消息内容。

**参数**：
| 参数名 | 类型 | 描述 |
|--------|------|------|
| text_content | `str` | 文本内容 |
| current_screenshot | `str` | 当前截图 |
| current_step | `int` | 当前步骤 |

**返回值**：`list` - 多模态消息内容，包含文本和图片

**格式**：
```
[
    {"type": "text", "text": "文本内容"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,...", "detail": "low"}},
    ...
]
```

#### _detect_loop()
**功能**：检测是否存在循环操作模式。

**返回值**：`bool` - 是否检测到循环

**检测逻辑**：
1. 检测长度为 2 的循环（A-B-A-B）
2. 检测长度为 3 的循环（A-B-C-A-B-C）
3. 检测连续相同操作

## 🚀 特性说明

### 多模态决策
- 结合文本和截图进行决策
- 支持历史截图上下文
- 智能理解页面状态

### 循环检测
- 自动检测循环操作模式
- 防止无限循环
- 提供警告和建议

### 滚动控制
- 智能跟踪滚动次数
- 防止无限滚动
- 记录页面滚动历史
- 提供滚动状态反馈

### 页面状态管理
- 跟踪当前页面 URL
- 检测页面切换
- 记录每个页面的滚动状态

### 历史记录管理
- 保存操作历史
- 保存截图历史
- 提供历史上下文

### 容错机制
- 自动推断缺失的 action 类型
- 处理无效响应
- 提供默认操作

### 智能提示
- 提供滚动警告
- 提供循环警告
- 提供目标文本发现提示

## 💡 使用示例

### 基本使用

```python
from autospider.extractor.llm.decider import LLMDecider
from autospider.common.types import AgentState, ScrollInfo

async def main():
    # 创建决策器实例
    decider = LLMDecider()
    
    # 模拟 Agent 状态
    state = AgentState(
        input={
            "task": "查找并点击登录按钮",
            "target_text": "欢迎登录",
            "max_steps": 20
        },
        page_url="https://example.com",
        page_title="示例网站",
        step_index=0,
        last_action=None,
        last_result=None
    )
    
    # 模拟滚动信息
    scroll_info = ScrollInfo(
        scroll_percent=50,
        is_at_top=False,
        is_at_bottom=False,
        can_scroll_up=True,
        can_scroll_down=True
    )
    
    # 获取决策
    action = await decider.decide(
        state=state,
        screenshot_base64="base64-encoded-screenshot",
        marks_text="1. 登录按钮 [按钮]\n2. 注册按钮 [按钮]",
        target_found_in_page=False,
        scroll_info=scroll_info
    )
    
    # 打印决策结果
    print(f"决策动作: {action.action}")
    print(f"思考过程: {action.thinking}")
    print(f"目标元素: {action.mark_id}")

if __name__ == "__main__":
    asyncio.run(main())
```

### 自定义配置

```python
from autospider.extractor.llm.decider import LLMDecider

async def main():
    # 使用自定义配置创建决策器
    decider = LLMDecider(
        api_key="your-api-key",
        api_base="https://api.example.com/v1",
        model="gpt-4",
        history_screenshots=5
    )
    
    # 设置任务计划
    decider.task_plan = "1. 导航到登录页面\n2. 输入用户名密码\n3. 点击登录按钮"
    
    # 后续使用同基本示例
    # ...

if __name__ == "__main__":
    asyncio.run(main())
```

## 🔍 最佳实践

### 模型选择
- 对于复杂任务，建议使用支持多模态的强大模型（如 GPT-4V）
- 对于简单任务，可以使用更高效的模型
- 根据实际需求调整温度参数，平衡创造力和准确性

### 截图处理
- 合理设置 history_screenshots 参数，平衡上下文和 token 消耗
- 历史截图使用低分辨率，当前截图使用高分辨率
- 定期清理截图历史，避免内存占用过高

### 循环检测
- 合理设置 max_consecutive_scrolls 参数，防止无限滚动
- 关注循环检测警告，及时调整策略

### 滚动控制
- 利用页面滚动历史，避免重复滚动同一页面
- 注意滚动警告，及时改变操作策略

### 容错机制
- 确保提供合理的默认操作
- 处理无效响应，避免系统崩溃

## 🐛 故障排除

### 问题：决策不准确

**可能原因**：
1. 模型能力不足
2. Prompt 设计不合理
3. 截图质量问题
4. 上下文信息不足

**解决方案**：
1. 尝试使用更强大的模型
2. 优化 Prompt 设计
3. 提高截图质量
4. 增加上下文信息

### 问题：循环操作

**可能原因**：
1. 页面结构复杂，模型无法找到目标
2. 目标不在当前页面
3. 操作序列设计不合理

**解决方案**：
1. 优化任务描述
2. 提供更详细的目标信息
3. 增加人工干预

### 问题：滚动无效果

**可能原因**：
1. 页面已滚动到底部
2. 页面是单页应用，滚动无效
3. 滚动方向错误

**解决方案**：
1. 检查滚动状态信息
2. 尝试其他操作，如点击链接
3. 调整滚动方向

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

### LLMDecider 类方法

| 方法名 | 参数 | 返回值 | 描述 |
|--------|------|--------|------|
| `__init__` | api_key=None, api_base=None, model=None, history_screenshots=3 | None | 初始化决策器 |
| `decide` | state, screenshot_base64, marks_text, target_found_in_page=False, scroll_info=None | `Action` | 根据当前状态和截图决定下一步操作 |
| `is_page_fully_scrolled` | page_url | `bool` | 检查页面是否已被完整滚动过 |
| `get_page_scroll_status` | page_url | `str` | 获取页面滚动状态描述 |
| `_build_user_message` | state, marks_text, target_found_in_page=False, scroll_info=None | `str` | 构建用户消息 |
| `_parse_response` | response_text | `Action` | 解析 LLM 响应 |
| `_build_multimodal_content` | text_content, current_screenshot, current_step | `list` | 构建包含历史截图的多模态消息内容 |
| `_detect_loop` | None | `bool` | 检测循环操作模式 |
| `_save_screenshot_to_history` | step, screenshot_base64, action, page_url | None | 保存截图到历史记录 |

## 🔄 依赖关系

- `langchain_core` - LangChain 核心库
- `langchain_openai` - OpenAI 集成
- `autospider.common.config` - 配置管理
- `autospider.common.types` - 类型定义
- `autospider.common.protocol` - 协议处理
- `autospider.extractor.llm.prompt_template` - Prompt 模板

## 📝 设计模式

- **多模态决策模式**：结合文本和图像进行决策
- **状态机模式**：根据当前状态决定下一步操作
- **观察者模式**：观察页面状态变化
- **策略模式**：支持不同的决策策略
- **容错模式**：处理无效响应和错误情况

## 🚀 性能优化

### 时间复杂度
- LLM 调用：O(1)（API 调用）
- 响应解析：O(n)，其中 n 是响应文本长度
- 循环检测：O(1)（固定长度历史检查）

### 空间复杂度
- O(n)，其中 n 是历史记录长度

### 优化建议

1. **减少 API 调用次数**：缓存常见决策
2. **优化 Prompt 结构**：减少不必要的 token 消耗
3. **合理设置历史长度**：平衡上下文和性能
4. **使用异步调用**：支持并发执行
5. **优化截图处理**：使用合适的分辨率和格式

## 📌 版本历史

| 版本 | 更新内容 | 日期 |
|------|----------|------|
| 1.0 | 初始版本 | 2026-01-01 |
| 1.1 | 增加循环检测 | 2026-01-10 |
| 1.2 | 优化滚动控制 | 2026-01-15 |
| 1.3 | 支持历史截图 | 2026-01-18 |
| 1.4 | 优化决策逻辑 | 2026-01-19 |

## 🔮 未来规划

- 支持更多模型提供商
- 优化循环检测算法
- 增加更多决策策略
- 支持个性化配置
- 提供决策解释
- 支持离线模式

## 📄 许可证

MIT License

---

最后更新: 2026-01-19