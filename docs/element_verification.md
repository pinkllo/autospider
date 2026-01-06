# 元素选择验证机制

## 问题背景

LLM 在处理截图时可能会识别错误的 `mark_id`，导致点击了错误的元素。例如：
- LLM 想点击"下一页"按钮（显示为 [5]）
- 但误选了 `mark_id: 6`
- 导致点击了错误的元素，任务失败

## 解决方案

实现了一个 **双重验证机制**，确保 LLM 选择的元素和它期望的文本内容匹配。

### 1. LLM 输出扩展

在 `Action` 类型中新增 `expected_text` 字段：

```python
class Action(BaseModel):
    action: ActionType
    mark_id: int | None
    expected_text: str | None  # 新增：期望的元素文本内容
    # ... 其他字段
```

LLM 现在必须输出：

```json
{
  "thinking": "我要点击下一页按钮",
  "action": "click",
  "mark_id": 5,
  "expected_text": "下一页"  // 必须填写看到的文本
}
```

### 2. 后台验证

在执行操作前，系统会：

1. **定位元素**：使用 XPath 或 data-som-id 定位元素
2. **提取文本**：获取元素的实际文本内容
3. **模糊匹配**：检查 `expected_text` 是否包含在实际文本中（不区分大小写）
4. **验证结果**：
   - ✅ **匹配成功**：继续执行操作
   - ❌ **匹配失败**：返回错误，要求 LLM 重新选择

### 3. 实现细节

#### 更新的 `find_element_by_xpath_list` 函数

```python
async def find_element_by_xpath_list(
    page: Page, 
    xpaths: list[str], 
    mark_id: int | None = None,
    expected_text: str | None = None,  # 新增参数
):
    """
    返回: (locator, used_xpath, verification_result)
    verification_result: {
        "verified": bool,        # 是否验证通过
        "actual_text": str,      # 实际元素文本
        "error": str | None      # 错误信息
    }
    """
```

#### ActionExecutor 中的验证逻辑

```python
# 执行点击前验证
locator, used_xpath, verification = await self._find_element_by_xpath_list(
    xpaths, action.mark_id, action.expected_text
)

# 检查验证结果
if not verification.get("verified", True):
    error_msg = f"元素验证失败: {verification.get('error')}"
    print(f"[Click] ⚠️ {error_msg}")
    return ActionResult(success=False, error=error_msg), None
```

### 4. Prompt 更新

在 `prompts/decider.yaml` 中添加了明确的说明：

```yaml
## 🔍 expected_text 说明（非常重要！）
- 当你选择一个元素时，必须填写 **expected_text** 字段
- 填入你在截图中看到的该元素的实际文字内容
- 例如：如果你选择了按钮 [5]，它显示"下一页"，则 expected_text 应该是 "下一页"
- 这用于验证你是否选对了元素，防止编号识别错误
- 对于没有文字的元素（如图标按钮），可以简短描述，如 "箭头" 或 "图标"
```

## 工作流程

```
1. LLM 观察截图
   ↓
2. LLM 决策: 点击元素 [5]，expected_text="下一页"
   ↓
3. 系统定位元素 [5]
   ↓
4. 系统提取元素文本: "下一页"
   ↓
5. 系统验证: "下一页" in "下一页" ✅
   ↓
6. 执行点击操作
```

**验证失败的情况**：

```
1. LLM 误选: mark_id=6, expected_text="下一页"
   ↓
2. 系统定位元素 [6]
   ↓
3. 系统提取元素文本: "上一页"
   ↓
4. 系统验证: "下一页" in "上一页" ❌
   ↓
5. 返回错误: "文本不匹配: 期望包含'下一页'，实际是'上一页'"
   ↓
6. LLM 重新决策
```

## 优势

1. **防止误选**：即使 LLM 识别错误的编号，也能及时发现
2. **自动纠错**：验证失败后，LLM 会收到明确的错误信息，可以重新选择
3. **提高可靠性**：减少因元素选择错误导致的任务失败
4. **调试友好**：验证日志清晰显示期望vs实际内容

## 使用示例

### 正确的 LLM 输出

```json
{
  "thinking": "我看到了'登录'按钮，编号是 [3]",
  "action": "click",
  "mark_id": 3,
  "expected_text": "登录"
}
```

### 错误会被捕获

```json
{
  "thinking": "我要点击下一页",
  "action": "click",
  "mark_id": 10,  // 实际上 [10] 是"上一页"
  "expected_text": "下一页"
}
```

系统会返回：
```
元素验证失败: 文本不匹配: 期望包含'下一页'，实际是'上一页'
```

## 注意事项

1. **模糊匹配**：使用 `in` 操作符和 `lower()` 进行不区分大小写的包含匹配
2. **空文本**：对于图标按钮等无文字元素，`expected_text` 可以为空或简短描述
3. **性能影响**：增加了一次 `inner_text()` 调用，但对整体性能影响很小
4. **兼容性**：对于不需要验证的操作（如 scroll、navigate），`expected_text` 可以为 None

## 修改的文件

1. `src/autospider/types.py` - 添加 `expected_text` 字段
2. `src/autospider/som/api.py` - 更新 `find_element_by_xpath_list` 函数，支持文本验证
3. `src/autospider/browser/actions.py` - 在操作执行前添加验证
4. `src/autospider/url_collector.py` - 更新 LLM 决策解析，添加 `expected_texts` 验证
5. `prompts/decider.yaml` - 更新 LLM prompt，要求返回 `expected_text`
6. `prompts/url_collector.yaml` - 更新 URL 收集器 prompt，要求返回 `expected_texts`

## 测试

```bash
# 测试 Action 类型
python -c "from src.autospider.types import Action; a = Action(action='click', mark_id=1, expected_text='test'); print(a.expected_text)"

# 测试函数导入
python -c "from src.autospider.som import find_element_by_xpath_list; print('OK')"

# 测试完整导入
python -c "from src.autospider.browser.actions import ActionExecutor; from src.autospider.url_collector import URLCollector; print('OK')"
```

## URL 收集器的验证机制

URL 收集器也支持元素验证，LLM 需要返回：

```json
{
  "action": "select_detail_links",
  "mark_ids": [40, 41, 42],
  "expected_texts": ["项目A标题", "项目B标题", "项目C标题"],
  "reasoning": "选择了3个项目链接"
}
```

系统会验证每个 `mark_id` 对应的元素文本是否与 `expected_texts` 匹配，只有通过验证的元素才会被处理。这确保了 LLM 选择的确实是正确的详情页链接，而不是其他无关元素。
