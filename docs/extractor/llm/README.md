# LLM 子模块

LLM 子模块提供与大语言模型交互的核心功能，包括 Prompt 模板渲染、LLM 调用和响应解析。该模块是 AutoSpider 智能决策的核心组件。

---

## 📁 模块结构

```
src/autospider/extractor/llm/
├── __init__.py              # 模块导出
├── llm_client.py           # LLM 客户端
├── prompt_renderer.py      # Prompt 渲染器
└── response_parser.py      # 响应解析器
```

---

## 📑 函数目录

### 🤖 LLM 客户端 (llm_client.py)
- `LLMClient` - LLM 客户端主类
- `call()` - 调用 LLM API
- `call_with_vision()` - 调用支持视觉的 LLM
- `stream()` - 流式调用 LLM

### 📝 Prompt 渲染器 (prompt_renderer.py)
- `PromptRenderer` - Prompt 渲染器主类
- `render()` - 渲染 Prompt 模板
- `render_from_file()` - 从文件渲染 Prompt
- `render_from_template()` - 从模板字符串渲染 Prompt

### 🔍 响应解析器 (response_parser.py)
- `ResponseParser` - 响应解析器主类
- `parse_action()` - 解析动作响应
- `parse_xpath()` - 解析 XPath 响应
- `parse_config()` - 解析配置响应
- `parse_url_list()` - 解析 URL 列表响应

---

## 🚀 核心功能

### LLM 客户端

LLMClient 提供与大语言模型交互的接口，支持文本和视觉输入。

```python
from autospider.extractor.llm import LLMClient

client = LLMClient(
    api_key="your-api-key",
    model="gpt-4-vision",
    temperature=0.1,
    max_tokens=4096
)

# 调用 LLM
response = await client.call(
    prompt="请分析这个页面的结构",
    image_base64="iVBORw0KGgoAAAANS..."
)

print(f"LLM 响应: {response}")
```

### Prompt 渲染器

PromptRenderer 负责渲染 Prompt 模板，支持变量替换和模板继承。

```python
from autospider.extractor.llm import PromptRenderer

renderer = PromptRenderer()

# 渲染 Prompt
prompt = renderer.render(
    template="请分析{{task}}，提取{{fields}}字段",
    variables={
        "task": "商品信息",
        "fields": "名称、价格、库存"
    }
)

print(f"渲染后的 Prompt: {prompt}")
```

### 响应解析器

ResponseParser 负责解析 LLM 的响应，提取结构化数据。

```python
from autospider.extractor.llm import ResponseParser

parser = ResponseParser()

# 解析动作响应
action = parser.parse_action(
    response='{"action": "click", "mark_id": 5, "thinking": "点击登录按钮"}'
)

print(f"动作: {action.action}")
print(f"标记ID: {action.mark_id}")
print(f"思考: {action.thinking}")
```

---

## 💡 特性说明

### 多模态支持

支持文本和图像输入，能够理解页面截图：

```python
# 带图像的 LLM 调用
response = await client.call_with_vision(
    prompt="请识别页面中的登录按钮",
    image_base64=screenshot_base64
)
```

### 模板系统

支持 Jinja2 模板语法，实现复杂的 Prompt 生成：

```python
# 使用 Jinja2 模板
template = """
任务: {{task}}
字段:
{% for field in fields %}
- {{field}}
{% endfor %}
"""

prompt = renderer.render(
    template=template,
    variables={
        "task": "采集商品信息",
        "fields": ["名称", "价格", "库存"]
    }
)
```

### 响应验证

自动验证 LLM 响应的格式和完整性：

```python
# 验证响应格式
try:
    action = parser.parse_action(response)
    print(f"解析成功: {action}")
except ValueError as e:
    print(f"解析失败: {e}")
```

---

## 🔧 使用示例

### 完整的 LLM 交互流程

```python
import asyncio
from autospider.extractor.llm import LLMClient, PromptRenderer, ResponseParser

async def analyze_page_with_llm(page):
    """使用 LLM 分析页面"""

    # 创建客户端
    client = LLMClient(
        api_key="your-api-key",
        model="gpt-4-vision",
        temperature=0.1
    )

    # 创建渲染器
    renderer = PromptRenderer()

    # 创建解析器
    parser = ResponseParser()

    # 获取页面截图
    screenshot = await page.screenshot(full_page=True)
    screenshot_base64 = base64.b64encode(screenshot).decode()

    # 渲染 Prompt
    prompt = renderer.render(
        template="请分析页面截图，识别{{element}}元素的位置",
        variables={"element": "登录按钮"}
    )

    # 调用 LLM
    response = await client.call_with_vision(
        prompt=prompt,
        image_base64=screenshot_base64
    )

    # 解析响应
    action = parser.parse_action(response)

    print(f"识别到的动作: {action.action}")
    print(f"标记ID: {action.mark_id}")

    return action

# 使用示例
asyncio.run(analyze_page_with_llm(page))
```

### 批量处理

```python
import asyncio
from autospider.extractor.llm import LLMClient

async def batch_process(pages):
    """批量处理多个页面"""

    client = LLMClient(
        api_key="your-api-key",
        model="gpt-4-vision"
    )

    async def process_page(page):
        """处理单个页面"""
        screenshot = await page.screenshot()
        screenshot_base64 = base64.b64encode(screenshot).decode()

        response = await client.call_with_vision(
            prompt="分析页面结构",
            image_base64=screenshot_base64
        )

        return response

    # 并发处理所有页面
    tasks = [process_page(page) for page in pages]
    results = await asyncio.gather(*tasks)

    return results

# 使用示例
results = asyncio.run(batch_process(pages))
```

---

## 📝 最佳实践

### Prompt 设计

1. **清晰明确**：使用清晰、具体的 Prompt
2. **结构化输出**：要求 LLM 输出结构化数据
3. **示例引导**：提供示例引导 LLM 理解
4. **约束条件**：明确说明约束条件

### LLM 调用

1. **温度设置**：根据任务调整 temperature 参数
2. **Token 限制**：合理设置 max_tokens 参数
3. **重试机制**：实现失败重试逻辑
4. **超时控制**：设置合理的超时时间

### 响应解析

1. **格式验证**：验证响应格式是否正确
2. **错误处理**：妥善处理解析错误
3. **默认值**：为可选字段提供默认值
4. **日志记录**：详细记录解析过程

---

## 🔍 故障排除

### 常见问题

1. **LLM 调用失败**
   - 检查 API Key 是否正确
   - 验证模型名称是否有效
   - 确认网络连接正常

2. **Prompt 渲染失败**
   - 检查模板语法是否正确
   - 验证变量是否完整
   - 确认模板文件路径正确

3. **响应解析失败**
   - 检查响应格式是否符合预期
   - 验证 JSON 结构是否正确
   - 确认解析器配置正确

### 调试技巧

```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 检查 LLM 响应
print(f"LLM 响应: {response}")
print(f"响应长度: {len(response)}")

# 检查 Prompt 渲染
print(f"渲染后的 Prompt: {prompt}")
print(f"Prompt 长度: {len(prompt)}")

# 检查解析结果
print(f"解析结果: {action}")
print(f"解析成功: {action is not None}")
```

---

*最后更新: 2026-01-08*
