# Protocol

`protocol.py` 模块定义了统一的 LLM 输出协议解析与兼容映射，确保不同版本的 LLM 输出能够被正确解析并映射到系统所需的结构中。

---

## 📁 模块信息

- **文件路径**: `src/autospider/common/protocol.py`
- **主要功能**: 
  - 定义 `ProtocolMessage` 数据模型。
  - 提供 LLM 文本解析工具，支持 JSON 提取、清理和抢救式解析。
  - 实现不同版本协议到旧版系统的兼容映射。

---

## 📑 核心类与函数

### 🏗️ 数据模型

#### `ProtocolMessage(BaseModel)`
标准协议消息模型。
- `protocol`: 协议版本标识（默认为 `autospider.protocol.v1`）。
- `action`: 动作类型。
- `args`: 动作参数字典。
- `thinking`: 思考过程（可选）。

---

### 🔍 解析工具

#### `parse_protocol_message(payload)`
统一协议解析入口。
- **输入**: 字符串、字典或 `None`。
- **输出**: 标准的 `action/args` 结构字典。
- **功能**: 处理原始 LLM 输出，尝试解析 JSON 并规范化字段。

#### `parse_json_dict_from_llm(text)`
从 LLM 文本中提取并解析 JSON。
- 采用三级解析策略：
  1. **括号匹配提取**: 确保提取完整的 JSON 对象。
  2. **贪婪正则匹配**: 最后的兜底匹配。
  3. **抢救式解析**: 针对格式错误的文本（如缺失引号、末尾多余逗号）进行字段级提取。

---

### 🔄 兼容映射 (Legacy Support)

为了支持旧的代码逻辑，模块提供了多个映射函数：

- `protocol_to_legacy_agent_action`: 映射到通用 Agent 的扁平结构。
- `protocol_to_legacy_url_decision`: 映射到 `URLCollector` 的决策结构。
- `protocol_to_legacy_pagination_result`: 映射分页按钮识别结果。
- `protocol_to_legacy_jump_widget_result`: 映射跳页控件识别结果。
- `protocol_to_legacy_field_nav_decision`: 映射字段导航阶段的决策。
- `protocol_to_legacy_field_extract_result`: 映射字段文本提取结果。

---

## 🚀 使用示例

```python
from autospider.common.protocol import parse_protocol_message

llm_output = """
思考：我需要点击搜索按钮。
```json
{
  "action": "click",
  "args": { "mark_id": 1, "target_text": "搜索" }
}
```
"""

result = parse_protocol_message(llm_output)
# Output:
# {
#   "action": "click",
#   "args": { "mark_id": 1, "target_text": "搜索" },
#   "thinking": "思考：我需要点击搜索按钮。"
# }
```
