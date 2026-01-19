# text_first.py - 文本优先的 mark_id 解析工具

text_first.py 模块提供文本优先的 mark_id 解析和消歧功能，用于处理 LLM 返回的 mark_id 与文本映射，提升视觉 LLM 决策的鲁棒性。

---

## 📁 文件路径

```
src/autospider/common/som/text_first.py
```

---

## 📑 函数目录

### 🚀 核心函数
- `resolve_mark_ids_from_map()` - 解析 LLM 返回的 mark_id_text_map（文本优先）
- `resolve_single_mark_id()` - 解析单个 mark_id（文本优先）
- `disambiguate_mark_id_by_text()` - 文本歧义时的重选机制

---

## 🚀 核心功能

### 文本优先的 mark_id 解析

该模块实现了“文本优先、歧义重选、未命中报错”的策略，用于处理视觉 LLM 常见的错误：文本选对了，但 mark_id 读错；或同一文本在页面多处出现导致歧义。

```python
from autospider.common.som.text_first import resolve_mark_ids_from_map

# 解析 LLM 返回的 mark_id_text_map（文本优先）
resolved_mark_ids = await resolve_mark_ids_from_map(
    page=page,
    llm=llm,
    snapshot=snapshot,
    mark_id_text_map={"5": "商品名称", "10": "价格"},
    max_retries=3
)

print(f"解析后的 mark_id: {resolved_mark_ids}")
```

### 单个 mark_id 解析

```python
from autospider.common.som.text_first import resolve_single_mark_id

# 解析单个 mark_id（文本优先）
resolved_mark_id = await resolve_single_mark_id(
    page=page,
    llm=llm,
    snapshot=snapshot,
    mark_id=5,
    target_text="商品名称",
    max_retries=3
)

print(f"解析后的 mark_id: {resolved_mark_id}")
```

### 文本歧义重选

当同一文本命中多个候选元素时，截图让 LLM 重选：

```python
from autospider.common.som.text_first import disambiguate_mark_id_by_text

# 文本歧义时的重选机制
selected_mark_id = await disambiguate_mark_id_by_text(
    page=page,
    llm=llm,
    candidates=candidates,
    target_text="商品名称",
    max_retries=3
)

if selected_mark_id:
    print(f"重选后的 mark_id: {selected_mark_id}")
else:
    print("重选失败")
```

---

## 💡 特性说明

### 文本优先策略

```python
# 核心策略：文本优先，mark_id 为辅
validator = MarkIdValidator()
resolved_mark_ids, results = await validator.validate_mark_id_text_map(
    mark_id_text_map, snapshot, page=page
)
```

### 歧义处理机制

当文本出现歧义时，使用新的截图让 LLM 重选：

```python
if r.status == "text_ambiguous" and r.candidate_mark_ids:
    candidates = [m for m in snapshot.marks if m.mark_id in set(r.candidate_mark_ids)]
    selected = await disambiguate_mark_id_by_text(
        page=page,
        llm=llm,
        candidates=candidates,
        target_text=r.llm_text,
        max_retries=retries,
    )
    if selected is not None:
        final_ids.append(selected)
```

### 容错机制

批量选择时，允许少量未命中不阻断全局流程：

```python
allow_partial = len(mark_id_text_map) > 1  # 批量选择时，允许少量未命中不阻断全局流程

# ...

if r.status == "text_not_found":
    if allow_partial:
        print(f"[TextFirst] ⚠ 未命中文本，已跳过该条: '{r.llm_text[:60]}'")
        continue
    raise ValueError(f"未在当前候选框中找到目标文本: '{r.llm_text}'")
```

### 去重机制

确保最终返回的 mark_id 列表中没有重复项：

```python
# 去重保持顺序
seen = set()
deduped: list[int] = []
for mid in final_ids:
    if mid not in seen:
        deduped.append(mid)
        seen.add(mid)
```

### 最小返回保障

即使允许 partial，也不能返回空集合，否则下游无可执行目标：

```python
if not deduped:
    # 修改原因：即使允许 partial，也不能返回空集合，否则下游无可执行目标
    raise ValueError("未能从当前候选框中解析出任何可用的 mark_id（文本匹配全部失败）")
```

---

## 🔧 使用示例

### 基本使用

```python
import asyncio
from autospider.common.som.text_first import resolve_mark_ids_from_map

async def example_usage(page, llm, snapshot):
    # LLM 返回的 mark_id 与文本映射
    mark_id_text_map = {
        "5": "商品名称",
        "10": "价格",
        "15": "库存"
    }

    # 解析 mark_id（文本优先）
    try:
        resolved_mark_ids = await resolve_mark_ids_from_map(
            page=page,
            llm=llm,
            snapshot=snapshot,
            mark_id_text_map=mark_id_text_map,
            max_retries=3
        )

        print(f"解析成功！mark_id: {resolved_mark_ids}")
        return resolved_mark_ids
    except ValueError as e:
        print(f"解析失败: {e}")
        return []

# 运行示例
asyncio.run(example_usage(page, llm, snapshot))
```

### 与动作执行器集成

```python
import asyncio
from autospider.common.som.text_first import resolve_single_mark_id
from autospider.common.browser.actions import ActionExecutor

async def integrated_usage(page, llm, snapshot, action):
    # 解析单个 mark_id（文本优先）
    resolved_mark_id = await resolve_single_mark_id(
        page=page,
        llm=llm,
        snapshot=snapshot,
        mark_id=action.mark_id,
        target_text=action.target_text,
        max_retries=3
    )

    # 使用解析后的 mark_id 执行动作
    action_executor = ActionExecutor(page)
    result, script_step = await action_executor.execute(
        action, 
        mark_id_to_xpath={resolved_mark_id: action.xpaths},
        step_index=1
    )

    return result, script_step

# 运行示例
asyncio.run(integrated_usage(page, llm, snapshot, action))
```

### 处理歧义情况

```python
import asyncio
from autospider.common.som.text_first import disambiguate_mark_id_by_text

async def ambiguity_handling_example(page, llm, snapshot, ambiguous_text):
    # 找到所有包含该文本的元素
    candidates = [
        mark for mark in snapshot.marks 
        if ambiguous_text in mark.text
    ]

    if len(candidates) > 1:
        print(f"发现 {len(candidates)} 个匹配的元素，需要重选")
        
        # 让 LLM 重选
        selected_mark_id = await disambiguate_mark_id_by_text(
            page=page,
            llm=llm,
            candidates=candidates,
            target_text=ambiguous_text,
            max_retries=3
        )

        if selected_mark_id:
            print(f"重选成功！选中的 mark_id: {selected_mark_id}")
            return selected_mark_id
        else:
            print("重选失败")
            return None
    else:
        print("没有歧义，直接返回")
        return candidates[0].mark_id if candidates else None

# 运行示例
asyncio.run(ambiguity_handling_example(page, llm, snapshot, "查看详情"))
```

---

## 📝 最佳实践

### 输入准备

1. **确保 snapshot 最新**：使用最新的页面快照，避免元素位置变化
2. **提供清晰的文本描述**：为每个 mark_id 提供准确的文本描述
3. **合理设置重试次数**：根据实际情况调整 max_retries 参数

### 错误处理

1. **捕获 ValueError**：处理解析失败的情况
2. **记录详细日志**：记录解析过程和结果，便于调试
3. **实现回退机制**：解析失败时提供备选方案

### 性能优化

1. **批量处理**：尽量使用 resolve_mark_ids_from_map 处理多个 mark_id
2. **限制候选数量**：避免过多候选元素影响性能
3. **合理设置超时**：根据网络情况和 LLM 响应速度调整超时

### 调试技巧

```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 打印解析结果
print(f"原始映射: {mark_id_text_map}")
print(f"解析后的 mark_id: {resolved_mark_ids}")

# 检查每个元素的匹配情况
for r in results:
    print(f"mark_id: {r.mark_id}, 文本: {r.llm_text}, 实际文本: {r.actual_text}, 相似度: {r.similarity:.2f}, 有效: {r.is_valid}")
```

---

## 🔍 故障排除

### 常见问题

1. **解析失败，返回空列表**
   - 检查文本描述是否准确
   - 验证页面快照是否最新
   - 增加重试次数

2. **歧义重选失败**
   - 检查候选元素是否清晰可见
   - 优化文本描述，使其更具体
   - 增加重试次数

3. **性能问题**
   - 减少候选元素数量
   - 优化 LLM 模型选择
   - 考虑使用更轻量级的验证策略

### 调试建议

```python
# 检查页面快照
print(f"快照 URL: {snapshot.url}")
print(f"元素数量: {len(snapshot.marks)}")

# 查看具体元素
for mark in snapshot.marks[:10]:  # 只显示前 10 个元素
    print(f"mark_id: {mark.mark_id}, 文本: {mark.text}, 标签: {mark.tag}")

# 检查 LLM 返回的映射
print(f"LLM 返回的映射: {mark_id_text_map}")
```

---

## 📚 函数参考

### resolve_mark_ids_from_map

```python
async def resolve_mark_ids_from_map(
    *, 
    page: "Page",
    llm: "ChatOpenAI",
    snapshot: "SoMSnapshot",
    mark_id_text_map: dict[str, str],
    max_retries: int | None = None
) -> list[int]
```

**参数说明**：
- `page`：Playwright Page 对象
- `llm`：ChatOpenAI 对象
- `snapshot`：SoMSnapshot 对象，页面元素快照
- `mark_id_text_map`：LLM 返回的 mark_id 与文本映射
- `max_retries`：最大重试次数（可选）

**返回值**：
- 去重后的最终 mark_id 列表

**异常**：
- `ValueError`：解析失败时抛出

### resolve_single_mark_id

```python
async def resolve_single_mark_id(
    *, 
    page: "Page",
    llm: "ChatOpenAI",
    snapshot: "SoMSnapshot",
    mark_id: int | None,
    target_text: str,
    max_retries: int | None = None
) -> int
```

**参数说明**：
- `page`：Playwright Page 对象
- `llm`：ChatOpenAI 对象
- `snapshot`：SoMSnapshot 对象，页面元素快照
- `mark_id`：LLM 返回的 mark_id（可选）
- `target_text`：目标文本描述
- `max_retries`：最大重试次数（可选）

**返回值**：
- 解析后的 mark_id

**异常**：
- `ValueError`：解析失败时抛出

### disambiguate_mark_id_by_text

```python
async def disambiguate_mark_id_by_text(
    *, 
    page: "Page",
    llm: "ChatOpenAI",
    candidates: list["ElementMark"],
    target_text: str,
    max_retries: int = 1
) -> int | None
```

**参数说明**：
- `page`：Playwright Page 对象
- `llm`：ChatOpenAI 对象
- `candidates`：候选元素列表
- `target_text`：目标文本描述
- `max_retries`：最大重试次数

**返回值**：
- 重选后的 mark_id，或 None（重选失败）

---

## 🛠️ 依赖关系

| 模块 | 用途 |
|------|------|
| `autospider.common.som.api` | SoM API 集成 |
| `autospider.extractor.validator.mark_id_validator` | mark_id 验证 |
| `autospider.extractor.llm.prompt_template` | 提示模板渲染 |
| `langchain_core` | LLM 消息处理 |
| `langchain_openai` | OpenAI LLM 集成 |
| `playwright` | 浏览器操作 |

---

## 📄 配置选项

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `url_collector.max_validation_retries` | int | 3 | 最大验证重试次数 |

---

*最后更新: 2026-01-19*