# Prompts 目录

本目录包含所有 LLM 模块使用的提示词（prompts）模板，采用 YAML 格式存储。

## 📁 文件列表

| 文件 | 用途 | 主要 Sections |
|------|------|---------------|
| `planner.yaml` | 任务规划器 | `system_prompt`, `user_prompt` |
| `decider.yaml` | LLM 决策器 | `system_prompt` |
| `url_collector.yaml` | URL 收集器 | `ask_llm_decision_system_prompt`, `ask_llm_decision_user_message`, `pagination_llm_system_prompt`, `pagination_llm_user_message` |
| `script_generator.yaml` | 脚本生成器 | `system_prompt`, `user_prompt` |

## 🎯 如何修改

直接编辑对应的 YAML 文件即可，无需修改代码。

**示例：**

```yaml
# planner.yaml

system_prompt: |
  你是一个专业的网页自动化任务规划专家。

user_prompt: |
  根据用户的任务描述和目标，分析任务并制定执行计划。
  
  ## 输入
  - 起始URL: {{start_url}}
  - 任务描述: {{task}}
  - 提取目标文本: {{target_text}}
  
  ## 输出要求
  以JSON格式输出任务规划...
```

## 🔄 变量语法

使用 `{{variable_name}}` 标记变量占位符。

系统会自动替换这些占位符为实际值。

**示例：**

```yaml
user_prompt: |
  当前页面: {{current_url}}
  任务描述: {{task_description}}
```

## ✅ 测试

修改后运行测试验证：

```bash
python tests/test_prompt_templates.py
```

## 📚 更多信息

- [完整使用指南](../docs/prompt_template_guide.md)
- [Prompt 管理快速参考](../docs/PROMPT_MANAGEMENT.md)
- [重构总结](../docs/prompt_refactor_summary.md)

## 💡 最佳实践

1. ✅ 使用 `#` 添加注释说明 prompt 的设计意图
2. ✅ 保持变量名清晰有意义（如 `{{task_description}}` 而不是 `{{x}}`）
3. ✅ 使用多行字符串 `|` 提高可读性
4. ✅ 修改后及时测试验证
5. ✅ 提交时写清楚变更原因

## ⚠️ 注意事项

- 模板文件使用 LRU 缓存，开发时修改后可能需要重启程序或清除缓存
- 变量名必须与代码中传入的参数名完全一致
- YAML 语法错误会导致加载失败，请确保格式正确
