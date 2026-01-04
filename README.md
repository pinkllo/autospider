# AutoSpider - 纯视觉 SoM 浏览器 Agent

基于 LangGraph + Playwright + 多模态 LLM 的纯视觉浏览器自动化 Agent。

## 核心特性

- **Set-of-Mark (SoM) 提示法**：在网页截图上覆盖数字编号的边界框，让 LLM 通过视觉识别进行决策
- **LangGraph 驱动**：observe → decide → act → check_done 循环
- **XPath 脚本沉淀**：执行过程自动生成可复用的 XPath 步骤集
- **遮挡检测**：只标注视口内且 Z 轴可见的元素
- **稳定 XPath 生成**：优先级降级策略（ID > data-testid > aria-label > text > relative path）

## 安装

```bash
# 创建 conda 环境
conda create -n autospider python=3.10 -y
conda activate autospider

# 安装依赖
pip install -e .

# 安装 Playwright 浏览器
playwright install chromium
```

## 配置

复制 `.env.example` 为 `.env` 并填写 OpenAI API Key：

```bash
cp .env.example .env
# 编辑 .env 文件，填写 OPENAI_API_KEY
```

## 使用

```bash
autospider \
  --start-url "https://example.com" \
  --task "点击登录按钮，输入用户名和密码" \
  --target-text "登录成功"
```

### 参数说明

| 参数 | 说明 | 必填 |
|------|------|------|
| `--start-url` | 起始 URL | ✅ |
| `--task` | 任务描述（自然语言） | ✅ |
| `--target-text` | 提取目标文本 | ✅ |
| `--max-steps` | 最大执行步数（默认 20） | ❌ |
| `--headless/--no-headless` | 无头模式（默认有头） | ❌ |
| `--output` | 输出 XPath 脚本路径 | ❌ |

## 输出

执行完成后会生成：

1. **XPath 脚本** (`output/script.json`)：可复用的自动化步骤
2. **截图序列** (`output/screenshots/`)：每一步的带标注截图
3. **执行日志** (`output/trace.log`)：详细执行轨迹

## 架构

```
observe (注入 SoM + 截图)
    ↓
decide (多模态 LLM 决策)
    ↓
act (执行动作 + 记录 XPath)
    ↓
check_done (校验完成条件)
    ↓
  [循环或结束]
```

## License

MIT
