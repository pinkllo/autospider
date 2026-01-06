# 验证错误反馈机制

## 概述

本文档描述了如何将元素验证失败的信息反馈给 LLM，让其能够从错误中学习并重新选择正确的元素。

## 工作流程

```
1. LLM 做决策 → 输出 mark_ids 和 expected_texts
                ↓
2. 系统验证   → 比较 expected_text 和实际元素文字
                ↓
3. 验证失败   → 错误信息存储在 last_verification_errors
                ↓
4. 下次决策   → 错误信息包含在 LLM prompt 中
                ↓
5. LLM 看到错误 → 重新检查截图，选择正确元素
```

## 实现细节

### 1. URL Collector 中的状态存储

在 `URLCollector` 类中添加了实例变量：

```python
self.last_verification_errors: list[str] = []
```

### 2. 探索阶段 (`_explore_phase`)

当验证失败时，收集错误信息：

```python
if expected.lower() not in actual.lower() and actual.lower() not in expected.lower():
    error_msg = f"[{candidate.mark_id}] 验证失败: 期望'{expected[:30]}' 实际'{actual[:30]}'"
    self.last_verification_errors.append(error_msg)
```

如果所有元素都验证失败，继续循环让 LLM 重新决策：

```python
if not candidates and self.last_verification_errors:
    print(f"[Explore] ⚠️ 所有元素均验证失败！将反馈给 LLM 重新选择")
    continue
```

### 3. 收集阶段 (`_collect_phase_with_llm`)

类似的验证逻辑：

```python
self.last_verification_errors = []
if expected_texts and len(expected_texts) == len(mark_ids):
    verified_candidates = []
    for candidate in candidates:
        # ... 验证逻辑
        if not verified:
            self.last_verification_errors.append(error_msg)
    candidates = verified_candidates
```

### 4. 翻页验证 (`_find_next_page_with_llm`)

翻页按钮的验证错误也会存储：

```python
if not verification.get("verified", True):
    error_msg = f"[{mark_id}] 翻页按钮验证失败: {verification.get('error')}"
    self.last_verification_errors = [error_msg]
    return False
```

### 5. LLM 决策提示 (`_ask_llm_for_decision`)

在 user message 中包含验证错误：

```python
verification_errors_section = ""
if self.last_verification_errors:
    verification_errors_section = f"""
## ⚠️ 上次元素验证失败详情（你选错了这些元素！）
{chr(10).join([f"  - {err}" for err in self.last_verification_errors])}

**请重新检查截图中的编号，确保选择正确的元素！** 
不要选择重复的元素编号，认真核对元素的文字内容。
"""
```

## 典型错误信息示例

```
[22] 验证失败: 期望'普陀区W060401单元...' 实际'机电设备'
[24] 验证失败: 期望'南汇生态专项...' 实际'交通系统'
[15] 翻页按钮验证失败: 期望'下一页' 实际'上一页'
```

## LLM 看到的 Prompt 示例

```
## 任务描述
收集招标公告详情页

## 当前页面 URL
https://example.com/list

## 已探索的详情页数量
5

## 已收集的 URL 示例（避免重复）
- https://example.com/detail/1
- https://example.com/detail/2

## ⚠️ 上次元素验证失败详情（你选错了这些元素！）
  - [22] 验证失败: 期望'普陀区W060401单元...' 实际'机电设备'
  - [24] 验证失败: 期望'南汇生态专项...' 实际'交通系统'

**请重新检查截图中的编号，确保选择正确的元素！** 
不要选择重复的元素编号，认真核对元素的文字内容。

请观察截图中红色边框标注的元素...
```

## 设计优势

### 1. 闭环反馈
- LLM 能看到自己犯的错误
- 避免重复相同的错误

### 2. 明确指示
- 错误信息包含 mark_id
- 显示期望文字 vs 实际文字
- 清晰的警告符号 ⚠️

### 3. 即时纠正
- 验证失败后立即重试
- 不需要人工干预

### 4. 适应性强
- 适用于探索阶段、收集阶段、翻页操作
- 支持不同类型的元素选择

## 配合其他机制

此机制与以下功能协同工作：

1. **XPath 优先策略** ([element_verification.md](element_verification.md))
   - 提供稳定的元素定位
   
2. **expected_text 验证**
   - 提供文本匹配检查
   
3. **视觉 LLM**
   - 基于截图做决策
   
4. **Prompt 模板** ([prompts/url_collector.yaml](../prompts/url_collector.yaml))
   - 要求 LLM 输出 expected_texts

## 错误处理流程

```python
# 1. LLM 决策
llm_decision = {
    "action": "select_detail_links",
    "mark_ids": [22, 24],
    "expected_texts": ["项目A", "项目B"]
}

# 2. 验证
for candidate in candidates:
    if expected_text not in actual_text:
        # 收集错误
        self.last_verification_errors.append(f"[{mark_id}] 验证失败: ...")
        
# 3. 过滤失败的元素
verified_candidates = [c for c in candidates if verified]

# 4. 如果全部失败，继续循环
if not verified_candidates and self.last_verification_errors:
    continue  # 下次调用 LLM 时会看到错误

# 5. 下次 LLM 决策时
# prompt 包含: "⚠️ 上次元素验证失败详情..."
```

## 测试建议

1. **故意选错**：修改 expected_texts 让验证失败
2. **观察日志**：查看 `[Explore] ✗ 元素 [22] 验证失败...`
3. **检查重试**：确认 LLM 在下次尝试时做出不同选择
4. **验证成功率**：统计验证通过/失败的比例

## 未来改进方向

1. **统计分析**：记录每个 mark_id 的失败次数
2. **学习机制**：识别 LLM 经常选错的元素类型
3. **视觉标注**：在截图上高亮上次失败的元素
4. **置信度评分**：LLM 输出选择的置信度，低置信度时更谨慎

## 相关文档

- [element_verification.md](element_verification.md) - 元素验证机制总览
- [prompts/url_collector.yaml](../prompts/url_collector.yaml) - URL 收集器提示词
- [prompts/decider.yaml](../prompts/decider.yaml) - 主决策器提示词
