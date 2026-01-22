# AutoSpider - 纯视觉 SoM 浏览器 Agent

基于 LangGraph + Playwright + 多模态 LLM 的纯视觉浏览器自动化 Agent。通过模拟人类视觉识别和操作习惯，AutoSpider 能够像真人一样理解网页、进行筛选引导，并最终自动生成稳健的爬虫脚本。

## 🚀 核心特性

### Set-of-Mark (SoM) 可视化标注
- **智能祖先检测**：自动识别可点击的父级容器，避免标注琐碎的子元素，操作更精准
- **多维度可见性校验**：结合视口检测、Z-index 遮挡分析及多点采样验证，确保只标注真人可见的元素
- **稳健 XPath 候选**：内置启发式算法，按优先级生成最稳定的定位器（ID > TestID > Aria-Label > Text > Relative Path）

### 全自动详情页 URL 批量收集
- **智能导航引导**：LLM 根据自然语言指令，自动在列表页进行复杂的点击筛选（如选择行业、结果状态等）
- **多策略分页识别**：支持 LLM 视觉识别 + 增强规则兜底双策略，智能处理各类分页控件（数字页码、跳转组件、下一页按钮等）
- **断点续传机制**：内置 Redis 持久化存储，支持中断后从断点继续采集，告别前功尽弃
- **自适应速率控制**：根据响应状态动态调整采集频率，平衡效率与稳定性

### 智能爬虫脚本生成
- **一键生成 Spider**：基于收集阶段沉淀的 XPaths 和 URL 列表，自动生成可独立运行的 Playwright 爬虫脚本
- **零模版依赖**：生成的脚本直接对接 `urls.txt`，极大提高大规模爬取的可靠性和成功率
- **模式沉淀与复用**：从探索阶段自动学习并固化页面交互模式，支持批量采集时高效复用

### 反反爬与容错机制
- **随机动作延迟**：模拟人类操作间隔，支持基础延迟 + 随机抖动配置
- **智能加载等待**：页面加载状态及 SPA 路由更新智能检测
- **多维容错策略**：
  - 智能跳跃策略（WidgetJumpStrategy）：处理弹窗、遮罩等干扰元素
  - URL 模式策略（URLPatternStrategy）：自动识别并跳过无效页面
  - 智能跳过策略（SmartSkipStrategy）：基于历史数据智能判断是否跳过异常项

### LangGraph 工作流驱动
- **Observe**：SoM 视觉标注页面元素
- **Decide**：LLM 理解任务并决策下一步操作
- **Act**：Playwright 执行动作（点击、输入、滚动、翻页等）
- **Check**：验证操作结果，触发下一步或结束任务

## 🛠️ 安装

```bash
# 创建并激活 conda 环境
conda create -n autospider python=3.10 -y
conda activate autospider

# 以开发模式安装包
pip install -e .

# 安装 Playwright 浏览器
playwright install chromium
```

## ⚙️ 配置

### 1. 环境变量 (.env)

复制 `.env.example` 为 `.env` 并根据实际使用的 LLM 提供商填写：

```bash
cp .env.example .env
```

**关键配置项：**
- `AIPING_API_KEY`: 多模态 LLM 的 API Key
- `AIPING_API_BASE`: API 基础路径（默认为 SiliconFlow）
- `AIPING_MODEL`: 使用的多模态模型（推荐 `zai-org/GLM-4.6V` 或其他支持视觉的模型）

### 2. 爬取行为配置

为了模拟人类行为并规避反爬，建议在 `.env` 中调整以下参数：

```env
# 基础操作延迟（秒）
ACTION_DELAY_BASE=1.0
# 延迟随机波动范围（秒）
ACTION_DELAY_RANDOM=0.5
# 页面加载等待时长（秒）
PAGE_LOAD_DELAY=1.5
# 滚动延迟
SCROLL_DELAY=0.5
# Redis 服务器地址（用于断点续传）
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
```

> [!TIP]
> 系统的所有内部默认值均在 `src/autospider/config.py` 中集中管理，遵循 Pydantic 定义。

## 📖 使用指南

### 1. 交互式任务运行 (`run`)

执行特定的一步或多步任务。

```bash
autospider run \
  --start-url "https://example.com" \
  --task "点击登录按钮，输入 xxx，并检查登录状态" \
  --target-text "欢迎登录"
```

### 2. 详情页 URL 批量收集 (`collect-urls`) ⭐

这是本项目的旗舰功能，分为四个阶段：**筛选导航 → 详情探索 → 模式提取 → 批量翻页收集**。

```bash
autospider collect-urls \
  --list-url "https://xxx.gov.cn/list" \
  --task "收集所有关于交通建设的招标公告详情页" \
  --explore-count 3
```

#### 工作流说明：

1. **引导阶段**：LLM 观察页面，自动点击筛选条件（如"进行中"、"交通运输"）
2. **探索阶段**：LLM 尝试点击并进入 N 个详情页，记录点击路径和页面模式
3. **沉淀阶段**：系统分析记录，提取稳定且通用的详情页 XPath、分页按钮 XPath 及干扰控件处理策略
4. **收集阶段**：
   - 利用提取的 XPath 高速遍历列表并自动翻页
   - 自动处理弹窗、遮罩等干扰元素
   - 支持中断后从断点继续（依赖 Redis）
   - 将所有 URL 保存到 `output/urls.txt`
5. **生成阶段**：自动生成 `output/spider.py`，用于后续内容的深度采集

#### 断点续传示例：

```bash
# 首次运行
autospider collect-urls --list-url "https://xxx" --task "xxx"

# 中断后恢复（自动从 Redis 读取断点）
autospider collect-urls --list-url "https://xxx" --task "xxx" --resume
```

### 3. 生成爬虫脚本 (`generate`)

基于收集的 URL 和 XPath 模式生成可独立运行的爬虫脚本：

```bash
autospider generate \
  --urls-file output/urls.txt \
  --output output/spider.py
```

## 📂 项目结构

```
autospider/
├── src/autospider/
│   ├── common/                 # 通用模块
│   │   ├── browser/           # 浏览器操作（动作执行、会话管理）
│   │   ├── som/               # Set-of-Mark 标注系统
│   │   ├── storage/           # 持久化存储（Redis 管理器）
│   │   ├── config.py          # 配置管理（Pydantic 模型）
│   │   └── types.py           # 类型定义
│   ├── crawler/               # 爬虫核心模块
│   │   ├── checkpoint/        # 断点恢复与速率控制
│   │   ├── batch_collector.py # 批量收集器
│   │   └── url_collector.py   # URL 收集器
│   ├── extractor/             # 提取与决策模块
│   │   ├── collector/         # 采集逻辑（分页、导航、URL 提取）
│   │   ├── graph/             # LangGraph 工作流
│   │   ├── llm/               # LLM 接口与 Prompt 模板
│   │   └── validator/         # 标注验证器
│   ├── cli.py                 # 命令行入口
│   └── __main__.py            # 模块入口
├── prompts/                   # Prompt 模板配置
├── tests/                     # 测试用例
└── docs/                      # 详细文档
```

## 🧩 核心模块说明

### 断点恢复系统 (checkpoint)
- `ResumeCoordinator`: 恢复协调中心，管理整体恢复流程
- `AdaptiveRateController`: 自适应速率控制器，根据响应动态调整
- `SmartSkipStrategy`: 基于历史数据的智能跳过策略
- `URLPatternStrategy`: URL 模式匹配，识别无效页面
- `WidgetJumpStrategy`: 处理弹窗、遮罩等干扰元素

### 分页处理 (pagination)
- 支持数字页码翻页（1, 2, 3...）
- 支持"下一页"按钮翻页
- 支持页码跳转组件（输入框 + 跳转按钮）
- 智能检测当前页码并计算目标页

### XPath 提取
- 多策略提取：LLM 视觉识别 + 规则兜底
- 稳定性评分与优先级排序
- 自动处理动态 ID 和随机类名

## 📝 依赖环境

- Python 3.10+
- Redis Server（用于断点续传，可选）
- 支持视觉的多模态 LLM API（如 SiliconFlow GLM-4.6V）

## � 许可证

MIT License

