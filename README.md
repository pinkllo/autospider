# AutoSpider - 纯视觉 SoM 浏览器 Agent

基于 LangGraph + Playwright + 多模态 LLM 的纯视觉浏览器自动化 Agent。

## 核心特性

- **Set-of-Mark (SoM) 提示法**：在网页截图上覆盖数字编号的边界框，让 LLM 通过视觉识别进行决策
- **LangGraph 驱动**：observe → decide → act → check_done 循环
- **XPath 脚本沉淀**：执行过程自动生成可复用的 XPath 步骤集
- **遮挡检测**：只标注视口内且 Z 轴可见的元素
- **稳定 XPath 生成**：优先级降级策略（ID > data-testid > aria-label > text > relative path）
- **详情页 URL 收集**：自动探索、分析模式、批量收集

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

### 1. 运行 Agent（原有功能）

执行特定任务并提取目标文本：

```bash
autospider run \
  --start-url "https://example.com" \
  --task "点击登录按钮，输入用户名和密码" \
  --target-text "登录成功"
```

### 2. 收集详情页 URL（新功能）

自动探索列表页，使用 LLM 根据任务描述智能识别详情链接模式，批量收集所有详情页 URL：

```bash
autospider collect-urls \
  --list-url "https://example.com/list" \
  --task "收集招标公告详情页" \
  --explore-count 3
```

#### 工作流程

1. **导航阶段**：LLM 根据你的任务描述，**先点击筛选条件**（如"已中标"、"交通运输"等标签）
2. **探索阶段**：进入 N 个不同的详情页，记录每次进入的操作步骤
3. **分析阶段**：分析这 N 次操作的共同模式，提取公共脚本
4. **收集阶段**：使用公共脚本遍历列表页，收集所有详情页的 URL

#### 参数说明

| 参数 | 说明 | 必填 |
|------|------|------|
| `--list-url` | 列表页 URL | ✅ |
| `--task` | 任务描述（自然语言），如"收集招标公告详情页" | ✅ |
| `--explore-count` | 探索几个详情页来提取模式（默认 3） | ❌ |
| `--headless/--no-headless` | 无头模式（默认有头） | ❌ |
| `--output` | 输出目录 | ❌ |

### 参数说明（run 命令）

| 参数 | 说明 | 必填 |
|------|------|------|
| `--start-url` | 起始 URL | ✅ |
| `--task` | 任务描述（自然语言） | ✅ |
| `--target-text` | 提取目标文本 | ✅ |
| `--max-steps` | 最大执行步数（默认 20） | ❌ |
| `--headless/--no-headless` | 无头模式（默认有头） | ❌ |
| `--output` | 输出 XPath 脚本路径 | ❌ |

## 输出

### run 命令输出

1. **XPath 脚本** (`output/script.json`)：可复用的自动化步骤
2. **截图序列** (`output/screenshots/`)：每一步的带标注截图
3. **执行日志** (`output/trace.log`)：详细执行轨迹

### collect-urls 命令输出

1. **URL 列表** (`output/urls.txt`)：收集到的所有详情页 URL（纯文本）
2. **详细结果** (`output/collected_urls.json`)：包含探索记录、公共模式、URL 列表的 JSON 文件
3. **截图序列** (`output/screenshots/`)：探索过程中的截图

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

