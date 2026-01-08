# decider.py - 多模态 LLM 决策器

decider.py 模块提供多模态 LLM 决策功能，根据页面截图和状态决定下一步操作。

---

## 📁 文件路径

```
src/autospider/extractor/llm/decider.py
```

---

## 📑 函数目录

### 🚀 核心类
- `LLMDecider` - 多模态 LLM 决策器

### 🔧 主要方法
- `decide()` - 根据当前状态和截图决定下一步操作
- `is_page_fully_scrolled()` - 检查页面是否已被完整滚动过
- `get_page_scroll_status()` - 获取页面滚动状态描述

### 🔍 内部方法
- `_build_user_message()` - 构建用户消息
- `_build_multimodal_content()` - 构建包含历史截图的多模态消息内容
- `_detect_loop()` - 检测是否存在循环操作模式
- `_parse_response()` - 解析 LLM 响应
- `_save_screenshot_to_history()` - 保存截图到历史记录

---

## 🚀 核心功能

### LLMDecider

多模态 LLM 决策器，根据页面截图和状态决定下一步操作。

```python
from autospider.extractor.llm.decider import LLMDecider

# 创建决策器
decider = LLMDecider()

# 根据当前状态和截图决定下一步操作
action = await decider.decide(
    state=agent_state,
    screenshot_base64=screenshot_base64,
    marks_text=marks_text,
    target_found_in_page=False,
    scroll_info=scroll_info
)

print(f"动作类型: {action.action}")
print(f"目标元素: {action.mark_id}")
print(f"思考过程: {action.thinking}")
```

### 多模态决策

结合历史截图和当前截图进行决策：

```python
# 构建包含历史截图的多模态消息内容
message_content = self._build_multimodal_content(
    user_content, 
    screenshot_base64, 
    state.step_index
)

# 返回格式: [text, image1, text1, image2, text2, ..., current_image]
```

### 循环检测

自动检测循环操作模式，避免陷入无限循环：

```python
def _detect_loop(self) -> bool:
    """检测是否存在循环操作模式"""
    # 检测长度为 2 的循环（A-B-A-B）
    if sigs[-1] == sigs[-3] and sigs[-2] == sigs[-4]:
        return True
    
    # 检测长度为 3 的循环（A-B-C-A-B-C）
    if sigs[-1] == sigs[-4] and sigs[-2] == sigs[-5] and sigs[-3] == sigs[-6]:
        return True
    
    # 检测连续相同操作
    if sigs[-1] == sigs[-2] == sigs[-3]:
        return True
    
    return False
```

### 滚动状态跟踪

跟踪页面滚动状态，避免无限滚动：

```python
# 更新页面滚动历史
if action.action == ActionType.SCROLL:
    self.scroll_count += 1
    
    # 如果连续滚动太多次，强制尝试其他操作
    if self.scroll_count >= self.max_consecutive_scrolls:
        print(f"[Decide] 警告: 已连续滚动 {self.scroll_count} 次")
```

---

## 💡 特性说明

### 历史截图支持

保存最近几步的截图，帮助 LLM 理解之前的操作：

```python
# 保存截图到历史记录
self._save_screenshot_to_history(
    step=state.step_index,
    screenshot_base64=screenshot_base64,
    action=action.action.value,
    page_url=page_url,
)

# 只保留最近 N 张截图
max_history = self.history_screenshots + 1
if len(self.screenshot_history) > max_history:
    self.screenshot_history = self.screenshot_history[-max_history:]
```

### 智能滚动管理

跟踪页面滚动状态，避免重复滚动：

```python
# 检查页面是否已被完整滚动过
def is_page_fully_scrolled(self, page_url: str) -> bool:
    """检查页面是否已被完整滚动过"""
    if page_url in self.page_scroll_history:
        return self.page_scroll_history[page_url].get("fully_scrolled", False)
    return False

# 获取页面滚动状态描述
def get_page_scroll_status(self, page_url: str) -> str:
    """获取页面滚动状态描述"""
    if page_url not in self.page_scroll_history:
        return "未滚动"
    
    history = self.page_scroll_history[page_url]
    if history.get("fully_scrolled"):
        return "✅ 已完整滚动（从顶到底再回顶）"
    elif history.get("reached_bottom"):
        return "⚠️ 已滚动到底部（但未滚回顶部）"
    else:
        return "部分滚动"
```

### 操作历史记录

记录所有操作历史，帮助 LLM 避免重复操作：

```python
# 记录到历史
self.action_history.append({
    "step": state.step_index,
    "action": action.action.value,
    "mark_id": action.mark_id,
    "target_text": action.target_text,
    "thinking": action.thinking,
    "page_url": page_url,
    "loop_detected": loop_detected,
})
```

### 响应解析与容错

自动解析 LLM 响应，并提供容错机制：

```python
def _parse_response(self, response_text: str) -> Action:
    """解析 LLM 响应"""
    # 清理 markdown 代码块标记
    code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', cleaned_text)
    
    # 尝试提取 JSON 对象
    json_match = re.search(r'\{[\s\S]*\}', cleaned_text)
    
    # 解析失败，返回 retry
    return Action(
        action=ActionType.RETRY,
        thinking=f"无法解析 LLM 响应: {response_text[:200]}",
    )
```

---

## 🔧 使用示例

### 基本使用

```python
import asyncio
from autospider.extractor.llm.decider import LLMDecider
from autospider.common.types import AgentState, ScrollInfo

async def make_decision():
    # 创建决策器
    decider = LLMDecider()

    # 根据当前状态和截图决定下一步操作
    action = await decider.decide(
        state=agent_state,
        screenshot_base64=screenshot_base64,
        marks_text=marks_text,
        target_found_in_page=False,
        scroll_info=ScrollInfo(
            scroll_percent=50,
            is_at_top=False,
            is_at_bottom=False,
            can_scroll_down=True,
            can_scroll_up=True
        )
    )

    print(f"动作类型: {action.action}")
    print(f"目标元素: {action.mark_id}")
    print(f"思考过程: {action.thinking}")

# 运行
asyncio.run(make_decision())
```

### 自定义历史截图数量

```python
# 自定义历史截图数量
decider = LLMDecider(history_screenshots=5)

# 决策时会发送最近 4 张历史截图 + 当前截图
action = await decider.decide(state, screenshot_base64, marks_text)
```

### 检查页面滚动状态

```python
# 检查页面是否已被完整滚动过
if decider.is_page_fully_scrolled(page_url):
    print("页面已完整滚动，不要再滚动")

# 获取页面滚动状态描述
status = decider.get_page_scroll_status(page_url)
print(f"页面滚动状态: {status}")
```

### 检测循环操作

```python
# 在决策过程中会自动检测循环操作
action = await decider.decide(state, screenshot_base64, marks_text)

# 检查历史记录中是否有循环
for h in decider.action_history:
    if h.get('loop_detected'):
        print(f"步骤 {h['step']} 检测到循环操作")
```

---

## 📝 最佳实践

### 决策优化

1. **提供清晰的上下文**：确保 marks_text 包含足够的元素信息
2. **使用历史截图**：利用历史截图帮助 LLM 理解之前的操作
3. **设置合理的滚动限制**：避免无限滚动

### 循环检测

1. **监控循环检测**：定期检查是否检测到循环操作
2. **调整检测策略**：根据实际情况调整循环检测策略
3. **处理循环情况**：在检测到循环时采取适当的措施

### 滚动管理

1. **跟踪滚动状态**：准确跟踪页面滚动状态
2. **避免重复滚动**：避免在已完整滚动的页面上重复滚动
3. **合理设置限制**：设置合理的滚动次数限制

### 历史管理

1. **合理设置历史长度**：根据任务复杂度设置历史截图数量
2. **定期清理历史**：避免历史记录过长影响性能
3. **利用历史信息**：充分利用历史信息帮助决策

---

## 🔍 故障排除

### 常见问题

1. **决策质量不佳**
   - 检查截图质量是否清晰
   - 验证 marks_text 是否准确
   - 确认是否提供了足够的上下文

2. **循环检测失效**
   - 检查操作签名生成逻辑是否正确
   - 验证循环检测算法是否合理
   - 确认历史记录是否完整

3. **滚动管理失效**
   - 检查滚动状态跟踪逻辑是否正确
   - 验证滚动限制设置是否合理
   - 确认滚动信息是否准确

4. **响应解析失败**
   - 检查 LLM 响应格式是否正确
   - 验证 JSON 解析逻辑是否正确
   - 确认容错机制是否生效

### 调试技巧

```python
# 检查决策器状态
print(f"当前页面 URL: {decider.current_page_url}")
print(f"滚动次数: {decider.scroll_count}")
print(f"最大连续滚动: {decider.max_consecutive_scrolls}")
print(f"历史操作数: {len(decider.action_history)}")
print(f"历史截图数: {len(decider.screenshot_history)}")

# 检查页面滚动历史
for page_url, history in decider.page_scroll_history.items():
    print(f"页面: {page_url[:50]}...")
    print(f"  完整滚动: {history.get('fully_scrolled')}")
    print(f"  到达底部: {history.get('reached_bottom')}")

# 检查循环检测
print(f"最近操作签名: {decider.recent_action_signatures}")
print(f"检测到循环: {decider._detect_loop()}")

# 检查 LLM 响应
print(f"LLM 响应: {response_text[:500]}...")
```

---

## 📚 方法参考

### LLMDecider 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `decide()` | state, screenshot_base64, marks_text, target_found_in_page, scroll_info | Action | 根据当前状态和截图决定下一步操作 |
| `is_page_fully_scrolled()` | page_url | bool | 检查页面是否已被完整滚动过 |
| `get_page_scroll_status()` | page_url | str | 获取页面滚动状态描述 |

### 初始化参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `api_key` | str | 从配置读取 | API Key |
| `api_base` | str | 从配置读取 | API Base URL |
| `model` | str | 从配置读取 | 模型名称 |
| `history_screenshots` | int | 3 | 发送最近几步的截图 |

---

## 📄 Prompt 模板

### decider.yaml

```yaml
system_prompt: |
  你是一个网页自动化操作专家，擅长分析网页截图并决定下一步操作。

  请根据提供的截图和元素列表，决定下一步操作。

user_prompt: |
  ## 任务目标
  {{task}}

  ## 提取目标
  精确匹配文本「{{target_text}}」

  ## 可交互元素列表
  {{marks_text}}

  ## 请分析截图并决定下一步操作
  以 JSON 格式输出你的决策。
```

---

*最后更新: 2026-01-08*
