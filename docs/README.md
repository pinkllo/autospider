# AutoSpider 文档

AutoSpider 是一个基于大语言模型的智能网页自动化工具，能够自动分析网页结构、提取数据并生成可执行的爬虫脚本。

---

## 📚 文档目录

### 🏗️ 核心模块
- [Common 模块](common/README.md) - 基础设施和公共工具
- [Crawler 模块](crawler/README.md) - 批量网页数据采集引擎
- [Extractor 模块](extractor/README.md) - 智能规则发现引擎
- [Prompts 模块](prompts/README.md) - 提示词管理中枢

### 🔧 工具模块
- [Utils 工具集](utils/README.md) - 通用工具函数
- [Browser Manager](browser_manager/README.md) - 浏览器管理

### 📋 配置与模板
- [Prompts 模板](prompts/README.md) - Prompt 模板文件
- [配置文件](config/README.md) - 系统配置说明

### 🧪 测试模块
- [测试框架](tests/README.md) - 单元测试和集成测试

---

## 🚀 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 基本使用

```python
from autospider import ConfigGenerator

generator = ConfigGenerator()
result = await generator.generate(
    list_url="https://example.com/products",
    task_description="采集商品信息"
)

print(f"生成的配置：{result.config}")
print(f"生成的脚本：{result.script}")
```

### 配置环境变量

复制 `.env.example` 文件为 `.env` 并配置必要的环境变量：

```bash
cp .env.example .env
# 编辑 .env 文件，设置 API Key 等配置
```

---

## 📖 模块说明

### Common 模块

提供项目的基础设施，包括配置管理、类型定义、浏览器操作、SoM 标注系统和存储管理。

### Crawler 模块

核心爬取引擎，负责执行批量网页数据采集任务，支持断点续传和速率控制。

### Extractor 模块

智能规则发现引擎，通过 LLM 理解页面语义，自动分析和提取关键信息。

### Prompts 模块

提示词管理中枢，包含所有与大语言模型交互的 Prompt 模板。

---

## 🔍 开发指南

### 项目结构

```
autospider/
├── src/autospider/          # 源代码
├── common/                  # 公共模块
├── docs/                    # 文档
├── prompts/                 # Prompt 模板
├── tests/                   # 测试代码
└── pyproject.toml          # 项目配置
```

### 代码规范

- 使用类型注解
- 遵循 PEP 8 代码风格
- 编写详细的文档字符串
- 添加必要的单元测试

### 测试运行

```bash
# 运行所有测试
pytest

# 运行特定模块测试
pytest tests/test_crawler.py
```

---

## 🤝 贡献指南

欢迎贡献代码！请遵循以下步骤：

1. Fork 项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

---

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

---

## 📞 联系方式

如有问题或建议，请通过以下方式联系：

- 提交 Issue
- 发送邮件
- 参与讨论

---

*最后更新: 2026-01-08*
